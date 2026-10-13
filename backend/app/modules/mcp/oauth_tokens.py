"""Authlib token operations over the existing isolated, bounded HTTP transport."""

import math
import time
from typing import Any

import httpx2
from authlib.integrations.base_client import OAuthError, UnsupportedTokenTypeError
from authlib.integrations.httpx_client import AsyncOAuth2Client
from fastapi import HTTPException, Request

from app.core.http_retry import retry_after_from_headers
from app.modules.auth.service import provider
from app.modules.mcp.network import PinnedTransport


class AuthorizationExpired(HTTPException):
    def __init__(self) -> None:
        super().__init__(409, "授权已失效，请重新连接")


class RefreshUnavailable(HTTPException):
    def __init__(self, seconds: int = 30) -> None:
        self.seconds = max(1, seconds)
        super().__init__(
            503,
            "授权服务暂不可用，凭据已保留，请稍后重试",
            headers={"Retry-After": str(self.seconds)},
        )


class TokenTransport(PinnedTransport):
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        response = await super().handle_async_request(request)
        # Authlib parses buffered JSON. Bound decoded data before returning to its client,
        # just as the former stream reader did; the shared transport still bounds wire data.
        body = bytearray()
        try:
            async for chunk in response.aiter_bytes(chunk_size=4096):
                if len(body) + len(chunk) > 65536:
                    raise RefreshUnavailable()
                body.extend(chunk)
        finally:
            await response.aclose()
        headers = dict(response.headers)
        headers.pop("content-encoding", None)
        headers.pop("content-length", None)
        return httpx2.Response(response.status_code, headers=headers, content=bytes(body))


def valid_secret(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value
        and len(value) <= 16384
        and all(33 <= ord(c) <= 126 for c in value)
    )


def normalize(result: dict[str, Any]) -> dict[str, Any]:
    if (
        not valid_secret(result.get("access_token"))
        or str(result.get("token_type", "Bearer")).lower() != "bearer"
        or ("refresh_token" in result and not valid_secret(result["refresh_token"]))
    ):
        raise RefreshUnavailable()
    try:
        expires = float(result.get("expires_in", 300))
        if not math.isfinite(expires):
            raise ValueError()
    except (ValueError, TypeError, OverflowError) as exc:
        raise RefreshUnavailable() from exc
    # Provider data cannot inject the platform's encrypted refresh state.
    values = {k: result[k] for k in ("access_token", "refresh_token", "scope") if k in result}
    values["token_type"] = "Bearer"
    values["expires_at"] = time.time() + min(max(expires, 0), 86400)
    return values


async def token_request(request: Request, url: str, payload: dict[str, str]) -> dict[str, Any]:
    def status(response: httpx2.Response) -> httpx2.Response:
        if response.status_code == 429 or response.status_code >= 500:
            raise RefreshUnavailable(retry_after_from_headers(response.headers) or 30)
        if response.status_code not in {200, 400, 401}:
            raise RefreshUnavailable()
        return response

    try:
        async with AsyncOAuth2Client(
            payload["client_id"],
            token_endpoint_auth_method="none",
            transport=TokenTransport(url, provider(request).settings),
            trust_env=False,
            follow_redirects=False,
            timeout=20,
            headers={"accept-encoding": "identity"},
        ) as client:
            client.register_compliance_hook("access_token_response", status)
            client.register_compliance_hook("refresh_token_response", status)
            if payload.get("grant_type") == "refresh_token":
                result = await client.refresh_token(url, refresh_token=payload["refresh_token"])
            else:
                result = await client.fetch_token(
                    url, **{k: v for k, v in payload.items() if k != "client_id"}
                )
        return normalize(dict(result))
    except (AuthorizationExpired, RefreshUnavailable):
        raise
    except HTTPException:
        raise RefreshUnavailable() from None
    except OAuthError as exc:
        if exc.error == "invalid_grant":
            raise AuthorizationExpired() from None
        raise RefreshUnavailable() from None
    except (
        httpx2.HTTPError,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        UnsupportedTokenTypeError,
    ):
        raise RefreshUnavailable() from None
