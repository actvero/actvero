"""OIDC authorization-code/PKCE and Keycloak's narrow provisioning boundary."""

import json
import logging
from typing import Any, cast
from urllib.parse import quote

import httpx
import httpx2
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from cryptography.fernet import Fernet
from fastapi import HTTPException
from joserfc import jwt
from joserfc.jwk import KeySet

from app.core.config import Settings


class IdentityProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def cipher(self) -> Fernet:
        secret = self.settings.session_encryption_key
        if secret is None:
            raise HTTPException(503, "会话加密尚未配置，请联系部署维护人员")
        return Fernet(secret.get_secret_value().encode())

    def seal(self, value: dict[str, Any]) -> str:
        return self.cipher().encrypt(json.dumps(value).encode()).decode()

    def unseal(self, value: str) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.cipher().decrypt(value.encode())))

    def internal(self, url: str) -> str:
        issuer = self.settings.oidc_issuer
        if not url.startswith(issuer + "/"):
            raise HTTPException(503, "身份服务端点与配置不一致")
        return (self.settings.oidc_internal_url or issuer) + url[len(issuer) :]

    async def metadata(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                self.internal(self.settings.oidc_issuer + "/.well-known/openid-configuration")
            )
            r.raise_for_status()
            result = cast(dict[str, Any], r.json())
        if result.get("issuer") != self.settings.oidc_issuer:
            raise HTTPException(503, "身份服务标识不匹配")
        for key in (
            "authorization_endpoint",
            "token_endpoint",
            "jwks_uri",
            "introspection_endpoint",
        ):
            self.internal(result[key])
        return result

    def client(self) -> AsyncOAuth2Client:
        secret = self.settings.web_client_secret
        if secret is None:
            raise HTTPException(503, "登录客户端尚未配置")
        return AsyncOAuth2Client(
            self.settings.web_client_id,
            secret.get_secret_value(),
            redirect_uri=self.settings.app_url + "/api/v1/auth/callback",
            scope="openid profile email",
            code_challenge_method="S256",
            timeout=10,
        )

    async def authorization(
        self, state: str, nonce: str, verifier: str, switch: bool, *, password: bool = False
    ) -> str:
        metadata = await self.metadata()
        async with self.client() as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_verifier=verifier,
                **({"prompt": "login"} if switch else {}),
                **({"kc_action": "UPDATE_PASSWORD"} if password else {}),
            )
            return str(url)

    async def exchange(
        self, code: str, verifier: str, nonce: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        metadata = await self.metadata()
        async with self.client() as client:
            token = await client.fetch_token(
                self.internal(metadata["token_endpoint"]), code=code, code_verifier=verifier
            )
        async with httpx.AsyncClient(timeout=10) as http:
            keys = await http.get(self.internal(metadata["jwks_uri"]))
            keys.raise_for_status()
        decoded = jwt.decode(
            token["id_token"], KeySet.import_key_set(keys.json()), algorithms=["RS256"]
        )
        claims = CodeIDToken(
            decoded.claims,
            decoded.header,
            options={
                "iss": {"essential": True, "value": self.settings.oidc_issuer},
                "aud": {"essential": True, "value": self.settings.web_client_id},
            },
            params={
                "nonce": nonce,
                "client_id": self.settings.web_client_id,
                "access_token": token["access_token"],
            },
        )
        claims.validate(leeway=30)
        return dict(token), dict(claims)

    async def refresh(self, token: dict[str, Any]) -> dict[str, Any]:
        metadata = await self.metadata()
        async with self.client() as client:

            def check_status(response: httpx2.Response) -> httpx2.Response:
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                return response

            client.register_compliance_hook("refresh_token_response", check_status)
            refreshed = await client.refresh_token(
                self.internal(metadata["token_endpoint"]), refresh_token=token["refresh_token"]
            )
        result = dict(refreshed)
        if "refresh_token" not in result:
            result["refresh_token"] = token["refresh_token"]
        return result

    async def inspect(self, token: dict[str, Any], subject: str) -> None:
        metadata = await self.metadata()
        secret = self.settings.web_client_secret
        if secret is None:
            raise HTTPException(503, "登录客户端尚未配置")
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                self.internal(metadata["introspection_endpoint"]),
                data={"token": token["access_token"], "token_type_hint": "access_token"},
                auth=(self.settings.web_client_id, secret.get_secret_value()),
            )
            r.raise_for_status()
        info = r.json()
        audience = info.get("aud", [])
        audience = [audience] if isinstance(audience, str) else audience
        if (
            info.get("active") is not True
            or info.get("sub") != subject
            or info.get("iss") != self.settings.oidc_issuer
            or "actvero-api" not in audience
            or info.get("client_id", info.get("azp")) != self.settings.web_client_id
        ):
            logging.getLogger(__name__).warning(
                "Token validation: active=%s subject=%s issuer=%s audience=%s client=%s",
                info.get("active") is True,
                info.get("sub") == subject,
                info.get("iss") == self.settings.oidc_issuer,
                "actvero-api" in audience,
                info.get("client_id", info.get("azp")) == self.settings.web_client_id,
            )
            raise HTTPException(401, "登录已失效，请重新登录")

    async def admin(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        secret = self.settings.provisioner_client_secret
        if secret is None:
            raise HTTPException(503, "成员身份管理尚未配置，请联系部署维护人员")
        issuer = self.settings.oidc_internal_url or self.settings.oidc_issuer
        base, realm = issuer.rsplit("/realms/", 1)
        async with httpx.AsyncClient(timeout=10) as client:
            token = await client.post(
                issuer + "/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.provisioner_client_id,
                    "client_secret": secret.get_secret_value(),
                },
            )
            token.raise_for_status()
            r = await client.request(
                method,
                base + "/admin/realms/" + quote(realm, safe="") + path,
                headers={"Authorization": "Bearer " + token.json()["access_token"]},
                **kwargs,
            )
        r.raise_for_status()
        return r

    async def user_enabled(self, subject: str) -> bool:
        try:
            r = await self.admin("GET", "/users/" + quote(subject, safe=""))
            return r.json().get("enabled") is True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            raise

    async def create_initial_user(
        self, email: str, name: str, password: str, registration_marker: str
    ) -> str:
        subject, _ = await self.create_managed_user(
            email, name, password, registration_marker, "actvero_setup", temporary=False
        )
        return subject

    async def create_member_user(
        self, email: str, name: str, password: str, marker: str
    ) -> tuple[str, bool]:
        return await self.create_managed_user(
            email, name, password, marker, "actvero_member", temporary=True
        )

    async def create_managed_user(
        self, email: str, name: str, password: str, marker: str, attribute: str, *, temporary: bool
    ) -> tuple[str, bool]:
        # Never adopt an identity or reset credentials merely because its email matches.
        users = (await self.admin("GET", "/users", params={"email": email, "exact": "true"})).json()
        reused = True
        if not users:
            try:
                await self.admin(
                    "POST",
                    "/users",
                    json={
                        "username": email,
                        "email": email,
                        "firstName": name,
                        "enabled": True,
                        "emailVerified": False,
                        "requiredActions": ["UPDATE_PASSWORD"] if temporary else [],
                        "attributes": {attribute: [marker]},
                        "credentials": [
                            {"type": "password", "value": password, "temporary": temporary}
                        ],
                    },
                )
                reused = False
            except httpx.HTTPStatusError as error:
                if error.response.status_code == 400:
                    raise HTTPException(422, "密码不符合身份服务策略或账号信息不完整") from None
                if error.response.status_code != 409:
                    raise
            users = (
                await self.admin("GET", "/users", params={"email": email, "exact": "true"})
            ).json()
        if not users:
            raise HTTPException(503, "身份服务尚未确认账号创建，请使用原信息重试")
        if (
            len(users) != 1
            or not users[0].get("enabled")
            or users[0].get("attributes", {}).get(attribute) != [marker]
        ):
            raise HTTPException(409, "此邮箱已有账号，请使用邀请加入或在成员列表中管理")
        return str(users[0]["id"]), reused

    async def prepare_user(self, email: str, name: str) -> tuple[str, bool]:
        users = (await self.admin("GET", "/users", params={"email": email, "exact": "true"})).json()
        if not users:
            try:
                await self.admin(
                    "POST",
                    "/users",
                    json={
                        "username": email,
                        "email": email,
                        "firstName": name or email.split("@")[0],
                        "enabled": True,
                        "emailVerified": False,
                        "requiredActions": ["VERIFY_EMAIL", "UPDATE_PASSWORD"],
                    },
                )
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 409:
                    raise
            users = (
                await self.admin("GET", "/users", params={"email": email, "exact": "true"})
            ).json()
        if len(users) != 1 or not users[0].get("enabled"):
            raise HTTPException(409, "该邮箱对应的登录身份不可用，请联系部署维护人员")
        user = users[0]
        return str(user["id"]), bool(user.get("requiredActions") or not user.get("emailVerified"))

    async def activation(self, subject: str, *, organization_invite: bool = False) -> None:
        user = (await self.admin("GET", "/users/" + quote(subject, safe=""))).json()
        if not user.get("enabled"):
            raise HTTPException(409, "该登录身份暂不可用")
        actions = list(
            dict.fromkeys(
                [
                    *user.get("requiredActions", []),
                    *([] if user.get("emailVerified") else ["VERIFY_EMAIL"]),
                ]
            )
        )
        if actions:
            await self.admin(
                "PUT",
                "/users/" + quote(subject, safe="") + "/execute-actions-email",
                params={
                    "client_id": self.settings.web_client_id,
                    "redirect_uri": self.settings.app_url
                    + ("/organization-invite" if organization_invite else "/join"),
                },
                json=actions,
            )

    async def configure_mail(self, settings: Settings) -> None:
        """Update only the realm mail transport, keeping identity policy intact."""
        smtp: dict[str, str] = {}
        if settings.smtp_host and settings.smtp_from:
            smtp = {
                "host": (settings.identity_smtp_loopback_host or settings.smtp_host)
                if settings.smtp_host in {"127.0.0.1", "localhost"}
                else settings.smtp_host,
                "port": str(
                    (settings.identity_smtp_loopback_port or settings.smtp_port)
                    if settings.smtp_host in {"127.0.0.1", "localhost"}
                    else settings.smtp_port
                ),
                "from": settings.smtp_from,
                "fromDisplayName": settings.smtp_display_name,
                "ssl": str(settings.smtp_ssl).lower(),
                "starttls": str(settings.smtp_starttls).lower(),
                "auth": str(bool(settings.smtp_username)).lower(),
            }
            if settings.smtp_username:
                smtp["user"] = settings.smtp_username
                smtp["password"] = (
                    settings.smtp_password.get_secret_value() if settings.smtp_password else ""
                )
        try:
            await self.admin("PUT", "", json={"smtpServer": smtp})
        except httpx.HTTPError:
            raise HTTPException(
                502, "身份邮件配置未同步，请联系部署管理员检查连接和配置权限"
            ) from None

    async def verify_email(self, subject: str, destination: str) -> None:
        try:
            await self.admin(
                "PUT",
                "/users/" + quote(subject, safe="") + "/execute-actions-email",
                params={
                    "client_id": self.settings.web_client_id,
                    "redirect_uri": self.settings.app_url + destination,
                    "lifespan": 1800,
                },
                json=["VERIFY_EMAIL"],
            )
        except httpx.HTTPError:
            raise HTTPException(502, "验证邮件发送失败，请稍后重试或联系平台运营人员") from None

    async def verified_email(self, subject: str, email: str) -> bool:
        value = (await self.admin("GET", "/users/" + quote(subject, safe=""))).json()
        return bool(
            value.get("enabled")
            and value.get("emailVerified")
            and str(value.get("email", "")).casefold() == email.casefold()
        )
