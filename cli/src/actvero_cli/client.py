import time
from typing import Any, cast
from uuid import uuid4

import httpx

from actvero_cli.errors import CliError
from actvero_cli.store import CredentialStore


def validate_tokens(value: dict[str, Any]) -> dict[str, Any]:
    if (
        value.get("scope") != "management:read"
        or not isinstance(value.get("access_token"), str)
        or not value["access_token"].startswith("avm_access_")
        or not isinstance(value.get("refresh_token"), str)
        or not value["refresh_token"].startswith("avm_refresh_")
        or not isinstance(value.get("expires_in"), int)
        or value["expires_in"] < 0
    ):
        raise CliError("invalid_response", "平台返回了不兼容的管理凭据")
    return value


class Client:
    def __init__(self, server: str, store: CredentialStore, http: httpx.Client | None = None):
        self.server, self.store = server, store
        self.http = http or httpx.Client(timeout=15, follow_redirects=False, trust_env=False)

    def close(self) -> None:
        self.http.close()

    def public(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.http.request(
                method, self.server + "/api/v1/management" + path, **kwargs
            )
        except httpx.HTTPError:
            raise CliError(
                "network_unavailable", "无法连接平台；请求结果未确认，请保留当前登录重试"
            ) from None
        try:
            result = response.json()
        except ValueError:
            raise CliError(
                "invalid_response", "平台未返回有效 JSON", status=response.status_code
            ) from None
        if not response.is_success:
            error = result.get("error", {}) if isinstance(result, dict) else {}
            if not isinstance(error, dict):
                error = {}
            raise CliError(
                str(error.get("code", "request_failed")),
                str(error.get("message", "平台拒绝了此请求")),
                status=response.status_code,
                request_id=response.headers.get("x-request-id", ""),
            )
        if not isinstance(result, dict):
            raise CliError("invalid_response", "平台返回格式不兼容")
        return result

    def save_login(self, tokens: dict[str, Any], instance_id: str) -> None:
        validate_tokens(tokens)
        self.store.save(
            {
                "tokens": tokens,
                "instance_id": instance_id,
                "access_deadline": time.time() + tokens["expires_in"],
                "pending": None,
                "ack": None,
            }
        )

    def _refresh(self, blob: dict[str, Any], *, recovery_rotation: bool = True) -> dict[str, Any]:
        pending = blob.get("pending")
        if not pending:
            pending = {"refresh_token": blob["tokens"]["refresh_token"], "request_id": str(uuid4())}
            blob["pending"] = pending
            # No request is sent unless its recovery identity has been durably stored.
            self.store.save(blob)
        result = validate_tokens(
            self.public("POST", "/refresh", json={**pending, "recovery_version": 2})
        )
        blob.update(
            {
                "tokens": result,
                "access_deadline": time.time() + result["expires_in"],
                "pending": None,
                "ack": result.get("refresh_request_id"),
            }
        )
        self.store.save(blob)
        self._acknowledge(blob)
        # Cached rotations may already have expired access; rotate the saved successor once.
        if blob["access_deadline"] <= time.time() + 10:
            if not recovery_rotation:
                raise CliError(
                    "invalid_response", "访问凭据连续过期，请检查平台时间和版本后重新登录"
                )
            return self._refresh(blob, recovery_rotation=False)
        return blob

    def _acknowledge(self, blob: dict[str, Any]) -> None:
        if blob.get("ack"):
            self.public(
                "POST",
                "/refresh/acknowledge",
                json={
                    "refresh_token": blob["tokens"]["refresh_token"],
                    "request_id": blob["ack"],
                },
            )
            blob["ack"] = None
            self.store.save(blob)

    def _tokens(self, *, force_refresh: bool = False) -> dict[str, Any]:
        blob = self.store.load()
        if not blob.get("tokens"):
            raise CliError("login_required", "请先执行 actvero auth login")
        validate_tokens(blob["tokens"])
        if blob.get("logout_pending"):
            raise CliError("logout_pending", "上次退出结果未确认，请先重试 auth logout")
        if (
            blob.get("pending")
            or force_refresh
            or blob.get("access_deadline", 0) <= time.time() + 10
        ):
            blob = self._refresh(blob)
        else:
            self._acknowledge(blob)
        return cast(dict[str, Any], blob["tokens"])

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        # A platform lock serializes renewal, not organization selection (there is none).
        with self.store.lock():
            tokens = self._tokens()
            try:
                return self.public(
                    "GET",
                    path,
                    params=params,
                    headers={
                        "Authorization": "Bearer " + tokens["access_token"],
                    },
                )
            except CliError as error:
                if error.code != "access_expired":
                    raise
                tokens = self._tokens(force_refresh=True)
                return self.public(
                    "GET",
                    path,
                    params=params,
                    headers={
                        "Authorization": "Bearer " + tokens["access_token"],
                    },
                )

    def logout(self) -> None:
        with self.store.lock():
            blob = self.store.load()
            if not blob.get("tokens"):
                return
            blob["logout_pending"] = True
            self.store.save(blob)
            self.public("POST", "/logout", json={"refresh_token": blob["tokens"]["refresh_token"]})
            self.store.clear()
