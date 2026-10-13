from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.jwk import KeySet

from app.modules.auth.oidc import IdentityProvider
from app.modules.desktop.errors import fail


class NativeIdentity:
    def __init__(
        self,
        provider: IdentityProvider,
        *,
        client_id: str | None = None,
        max_age_seconds: int | None = None,
    ):
        self.provider = provider
        self.settings = provider.settings
        self.client_id = client_id or self.settings.desktop_client_id
        self.max_age_seconds = (
            max_age_seconds
            if max_age_seconds is not None
            else self.settings.desktop_session_hours * 3600
        )

    def client(self, redirect_uri: str) -> AsyncOAuth2Client:
        return AsyncOAuth2Client(
            self.client_id,
            token_endpoint_auth_method="none",
            redirect_uri=redirect_uri,
            scope="openid profile email",
            code_challenge_method="S256",
            timeout=10,
        )

    async def authorization(
        self, redirect_uri: str, state: str, nonce: str, challenge: str, reauthenticate: bool
    ) -> str:
        metadata = await self.provider.metadata()
        async with self.client(redirect_uri) as client:
            url, _ = client.create_authorization_url(
                metadata["authorization_endpoint"],
                state=state,
                nonce=nonce,
                code_challenge=challenge,
                code_challenge_method="S256",
                # OIDC requires auth_time when max_age is requested, including SSO reuse.
                max_age=0 if reauthenticate else self.max_age_seconds,
                **({"prompt": "login"} if reauthenticate else {}),
            )
        return str(url)

    async def exchange(
        self, code: str, verifier: str, nonce: str, redirect_uri: str
    ) -> dict[str, Any]:
        metadata = await self.provider.metadata()
        async with self.client(redirect_uri) as client:
            token = await client.fetch_token(
                self.provider.internal(metadata["token_endpoint"]),
                code=code,
                code_verifier=verifier,
            )
        async with httpx.AsyncClient(timeout=10) as http:
            keys = await http.get(self.provider.internal(metadata["jwks_uri"]))
            keys.raise_for_status()
        decoded = jwt.decode(
            token["id_token"], KeySet.import_key_set(keys.json()), algorithms=["RS256"]
        )
        claims = CodeIDToken(
            decoded.claims,
            decoded.header,
            options={
                "iss": {"essential": True, "value": self.settings.oidc_issuer},
                "aud": {"essential": True, "value": self.client_id},
                "auth_time": {"essential": True},
                "nonce": {"essential": True, "value": nonce},
            },
            params={
                "nonce": nonce,
                "client_id": self.client_id,
                "access_token": token["access_token"],
            },
        )
        claims.validate(leeway=30)
        if (
            claims.get("azp", self.client_id) != self.client_id
            or not isinstance(claims.get("auth_time"), (int, float))
            or claims["auth_time"] <= 0
            or claims["auth_time"] > datetime.now(UTC).timestamp() + 30
        ):
            fail(401, "invalid_login", "登录验证失败，请重新登录")
        # Upstream credentials are used only inside the verified code exchange and discarded.
        return dict(claims)

    async def account_valid(self, subject: str, authenticated_at: datetime) -> None:
        try:
            response = await self.provider.admin("GET", "/users/" + quote(subject, safe=""))
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 404:
                fail(401, "account_unavailable", "账号已不可用")
            raise
        user = response.json()
        if not user.get("enabled"):
            fail(401, "account_unavailable", "账号已不可用")
        if user.get("requiredActions") or user.get("notBefore", 0) > authenticated_at.timestamp():
            fail(401, "reauthentication_required", "账号需要重新验证，请重新登录")
