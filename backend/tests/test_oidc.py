import time
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import HTTPException
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey

from app.core.config import Settings
from app.modules.auth.oidc import IdentityProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["issuer", "audience", "nonce", "expired", "signature", None])
async def test_signed_id_token_validation(monkeypatch, invalid):
    settings = Settings(_env_file=None, web_client_secret="test")
    provider = IdentityProvider(settings)
    key = RSAKey.generate_key(2048)
    signing_key = RSAKey.generate_key(2048) if invalid == "signature" else key
    claims = {
        "iss": settings.oidc_issuer,
        "aud": settings.web_client_id,
        "sub": "subject",
        "exp": int(time.time()) + 300,
        "iat": int(time.time()),
        "nonce": "nonce",
    }
    if invalid in {"issuer", "audience", "nonce"}:
        claims[{"issuer": "iss", "audience": "aud", "nonce": "nonce"}[invalid]] = "wrong"
    if invalid == "expired":
        claims["exp"] = int(time.time()) - 120
    signed = jwt.encode({"alg": "RS256"}, claims, signing_key)
    oauth = AsyncMock()
    oauth.__aenter__.return_value = oauth
    oauth.fetch_token.return_value = {"id_token": signed, "access_token": "access"}
    monkeypatch.setattr(provider, "client", lambda: oauth)
    metadata = {
        "token_endpoint": settings.oidc_issuer + "/token",
        "jwks_uri": settings.oidc_issuer + "/keys",
    }
    monkeypatch.setattr(provider, "metadata", AsyncMock(return_value=metadata))
    http = AsyncMock()
    http.__aenter__.return_value = http
    http.get.return_value = httpx.Response(
        200,
        json={"keys": [key.as_dict(private=False)]},
        request=httpx.Request("GET", metadata["jwks_uri"]),
    )
    monkeypatch.setattr("app.modules.auth.oidc.httpx.AsyncClient", MagicMock(return_value=http))
    if invalid:
        with pytest.raises(JoseError):
            await provider.exchange("code", "verifier", "nonce")
    else:
        _, result = await provider.exchange("code", "verifier", "nonce")
        assert result["sub"] == "subject"
        assert oauth.fetch_token.call_args.kwargs["code_verifier"] == "verifier"


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["active", "sub", "iss", "aud", "client_id", None])
async def test_introspection_checks_active_subject_issuer_audience_and_client(monkeypatch, field):
    settings = Settings(_env_file=None, web_client_secret="test")
    provider = IdentityProvider(settings)
    data = {
        "active": True,
        "sub": "subject",
        "iss": settings.oidc_issuer,
        "aud": ["actvero-api"],
        "client_id": settings.web_client_id,
    }
    if field:
        data[field] = False if field == "active" else "wrong"
    endpoint = settings.oidc_issuer + "/introspect"
    monkeypatch.setattr(
        provider, "metadata", AsyncMock(return_value={"introspection_endpoint": endpoint})
    )
    http = AsyncMock()
    http.__aenter__.return_value = http
    http.post.return_value = httpx.Response(200, json=data, request=httpx.Request("POST", endpoint))
    monkeypatch.setattr("app.modules.auth.oidc.httpx.AsyncClient", MagicMock(return_value=http))
    if field:
        with pytest.raises(HTTPException) as error:
            await provider.inspect({"access_token": "test"}, "subject")
        assert error.value.status_code == 401
    else:
        await provider.inspect({"access_token": "test"}, "subject")


@pytest.mark.asyncio
@pytest.mark.parametrize("temporary", [True, False])
async def test_managed_account_credentials_and_recovery_never_reset_password(temporary):
    provider = IdentityProvider(Settings(_env_file=None))
    attribute = "actvero_member" if temporary else "actvero_setup"
    account = {"id": "subject", "enabled": True, "attributes": {attribute: ["marker"]}}
    provider.admin = AsyncMock(
        side_effect=[
            httpx.Response(200, json=[]),
            httpx.Response(201),
            httpx.Response(200, json=[account]),
        ]
    )
    if temporary:
        assert await provider.create_member_user(
            "test@example.com", "姓名", "test-password", "marker"
        ) == ("subject", False)
    else:
        assert (
            await provider.create_initial_user(
                "test@example.com", "姓名", "test-password", "marker"
            )
            == "subject"
        )
    create = provider.admin.call_args_list[1]
    assert create.args == ("POST", "/users")
    body = create.kwargs["json"]
    assert body["credentials"] == [
        {"type": "password", "value": "test-password", "temporary": temporary}
    ]
    assert body["requiredActions"] == (["UPDATE_PASSWORD"] if temporary else [])
    assert body["emailVerified"] is False
    provider.admin = AsyncMock(return_value=httpx.Response(200, json=[account]))
    result = await provider.create_managed_user(
        "test@example.com", "姓名", "changed-password", "marker", attribute, temporary=temporary
    )
    assert result == ("subject", True)
    assert provider.admin.call_count == 1
    assert provider.admin.call_args.args[0] == "GET"


@pytest.mark.asyncio
async def test_direct_account_never_adopts_unrelated_email_identity():
    provider = IdentityProvider(Settings(_env_file=None))
    provider.admin = AsyncMock(
        return_value=httpx.Response(200, json=[{"id": "existing", "enabled": True}])
    )
    with pytest.raises(HTTPException) as error:
        await provider.create_member_user("existing@example.com", "姓名", "test-password", "marker")
    assert error.value.status_code == 409
    assert provider.admin.call_count == 1
    assert provider.admin.call_args.args[0] == "GET"


@pytest.mark.asyncio
async def test_direct_account_uncertain_readback_is_retryable():
    provider = IdentityProvider(Settings(_env_file=None))
    provider.admin = AsyncMock(
        side_effect=[
            httpx.Response(200, json=[]),
            httpx.Response(201),
            httpx.Response(200, json=[]),
        ]
    )
    with pytest.raises(HTTPException) as error:
        await provider.create_member_user("test@example.com", "姓名", "test-password", "marker")
    assert error.value.status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 200])
async def test_locked_authlib_refresh_status_and_omitted_refresh_token(monkeypatch, status):
    import httpx2
    from authlib.integrations.httpx_client import AsyncOAuth2Client

    provider = IdentityProvider(Settings(_env_file=None, web_client_secret="test"))
    endpoint = provider.settings.oidc_issuer + "/token"
    monkeypatch.setattr(provider, "metadata", AsyncMock(return_value={"token_endpoint": endpoint}))

    def reply(request):
        return httpx2.Response(
            status,
            headers={"Retry-After": "3600"},
            json={
                "access_token": "new",
                "token_type": "Bearer",
                "expires_in": 300,
            }
            if status == 200
            else {"error": "temporarily_unavailable"},
            request=request,
        )

    monkeypatch.setattr(
        provider,
        "client",
        lambda: AsyncOAuth2Client("test", "test", transport=httpx2.MockTransport(reply)),
    )
    if status != 200:
        with pytest.raises(httpx2.HTTPStatusError) as caught:
            await provider.refresh({"refresh_token": "original"})
        assert caught.value.response.status_code == status
        assert caught.value.response.headers["Retry-After"] == "3600"
    else:
        result = await provider.refresh({"refresh_token": "original"})
        assert result["refresh_token"] == "original"
        assert result["access_token"] == "new"
