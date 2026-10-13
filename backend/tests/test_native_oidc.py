import time
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from authlib.common.errors import AuthlibBaseError
from fastapi import HTTPException
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey

from app.core.config import Settings
from app.modules.auth.oidc import IdentityProvider
from app.modules.auth.service import now
from app.modules.desktop.oidc import NativeIdentity


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid",
    ["iss", "aud", "nonce", "azp", "expired", "signature", "auth_time", "missing_nonce", None],
)
async def test_native_signed_claims_and_public_pkce_exchange(monkeypatch, invalid):
    upstream = IdentityProvider(Settings(_env_file=None))
    native = NativeIdentity(upstream)
    key = RSAKey.generate_key(2048)
    signing_key = RSAKey.generate_key(2048) if invalid == "signature" else key
    claims = {
        "iss": upstream.settings.oidc_issuer,
        "aud": "actvero-desktop",
        "sub": "test-subject",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "auth_time": int(time.time()),
        "nonce": "expected-nonce",
        "azp": "actvero-desktop",
    }
    if invalid in {"iss", "aud", "nonce", "azp"}:
        claims[invalid] = "wrong"
    if invalid == "expired":
        claims["exp"] = int(time.time()) - 120
    if invalid == "auth_time":
        del claims["auth_time"]
    if invalid == "missing_nonce":
        del claims["nonce"]
    signed = jwt.encode({"alg": "RS256"}, claims, signing_key)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.fetch_token.return_value = {
        "id_token": signed,
        "access_token": "upstream-access",
        "refresh_token": "upstream-refresh",
    }
    monkeypatch.setattr(native, "client", lambda uri: client)
    metadata = {
        "token_endpoint": upstream.settings.oidc_issuer + "/token",
        "jwks_uri": upstream.settings.oidc_issuer + "/keys",
    }
    upstream.metadata = AsyncMock(return_value=metadata)
    http = AsyncMock()
    http.__aenter__.return_value = http
    http.get.return_value = httpx.Response(
        200,
        json={"keys": [key.as_dict(private=False)]},
        request=httpx.Request("GET", metadata["jwks_uri"]),
    )
    monkeypatch.setattr("app.modules.desktop.oidc.httpx.AsyncClient", MagicMock(return_value=http))
    if invalid:
        with pytest.raises((AuthlibBaseError, JoseError, HTTPException)):
            await native.exchange(
                "authorization-code",
                "verifier",
                "expected-nonce",
                "http://127.0.0.1:49201/actvero/callback",
            )
    else:
        result = await native.exchange(
            "authorization-code",
            "verifier",
            "expected-nonce",
            "http://127.0.0.1:49201/actvero/callback",
        )
        assert result["sub"] == "test-subject"
        assert "access_token" not in result and "refresh_token" not in result
        assert client.fetch_token.call_args.kwargs["code_verifier"] == "verifier"


@pytest.mark.asyncio
@pytest.mark.parametrize("account_case", ["disabled", "revoked", "password_change"])
async def test_upstream_account_revocation_and_required_actions(account_case):
    # Construct the revocation timestamp at execution, not collection; the full
    # integration suite can take longer than the original 100-second offset.
    account = {
        "disabled": {"enabled": False},
        "revoked": {"enabled": True, "notBefore": int(time.time()) + 100},
        "password_change": {"enabled": True, "requiredActions": ["UPDATE_PASSWORD"]},
    }[account_case]
    provider = IdentityProvider(Settings(_env_file=None))
    provider.admin = AsyncMock(return_value=httpx.Response(200, json=account))
    with pytest.raises(HTTPException) as error:
        await NativeIdentity(provider).account_valid("subject", now() - timedelta(seconds=10))
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_authorization_always_requests_auth_time_and_public_s256():
    from urllib.parse import parse_qs, urlsplit

    provider = IdentityProvider(Settings(_env_file=None))
    provider.metadata = AsyncMock(
        return_value={"authorization_endpoint": "https://login.example/auth"}
    )
    native = NativeIdentity(provider)
    for fresh in (False, True):
        url = await native.authorization(
            "http://127.0.0.1:49201/actvero/callback", "state", "nonce", "challenge", fresh
        )
        query = parse_qs(urlsplit(url).query)
        assert query["client_id"] == ["actvero-desktop"]
        assert query["code_challenge_method"] == ["S256"]
        assert query["code_challenge"] == ["challenge"]
        assert query["nonce"] == ["nonce"]
        assert query["max_age"] == [
            "0" if fresh else str(provider.settings.desktop_session_hours * 3600)
        ]
        assert "client_secret" not in query
