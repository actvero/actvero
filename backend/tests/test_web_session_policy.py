"""Rolling sessions, permanent vs temporary identity failure and process-safe rotation."""

import asyncio
import time
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from authlib.integrations.base_client.errors import OAuthError
from test_identity_access import env as identity_env
from test_identity_access import exchange_as

from app.modules.auth.models import WebSession
from app.modules.auth.service import COOKIE, now
from app.modules.auth.session_policy import initialize

env = identity_env
pytestmark = pytest.mark.asyncio


async def persistent(env, *, age=1, remaining=3):
    env.provider.settings.web_session_policy = "persistent"
    user = await env.client()
    raw = user.api.cookies.get(COOKIE)
    # Mirror browser domain/path scoping when the server renews the cookie.
    user.api.cookies.clear()
    user.api.cookies.set(COOKIE, raw, domain="127.0.0.1", path="/")
    async with env.sessions() as db:
        row = await db.get(WebSession, user.session.id)
        row.authenticated_at = now() - timedelta(days=age)
        initialize(row, env.provider.settings, row.authenticated_at)
        row.expires_at = now() + timedelta(days=remaining)
        row.renewed_at = now() - timedelta(minutes=6)
        await db.commit()
    return user


async def stored(env, user):
    async with env.sessions() as db:
        return await db.get(WebSession, user.session.id)


async def expire_access(env, user):
    async with env.sessions() as db:
        row = await db.get(WebSession, user.session.id)
        row.tokens = env.provider.seal(
            {"access_token": "old", "refresh_token": "old-r", "expires_at": 1}
        )
        await db.commit()


async def test_active_persistent_session_renews_after_eight_hours_and_preserves_page_authority(env):
    user = await persistent(env)
    response = await user.api.get("/api/v1/auth/session")
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["session_policy"] == "persistent"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    row = await stored(env, user)
    assert row.expires_at > now() + timedelta(days=29, hours=23)
    assert row.absolute_expires_at < now() + timedelta(days=90)
    assert row.identity_id == user.identity.id
    assert row.csrf == user.session.csrf


async def test_no_extra_rotation_or_extension_for_every_minute_poll(env):
    user = await persistent(env)
    await user.api.get("/api/v1/auth/session")
    first = await stored(env, user)
    await user.api.get("/api/v1/auth/session")
    second = await stored(env, user)
    assert (first.expires_at, first.renewed_at) == (second.expires_at, second.renewed_at)


async def test_persistent_cap_is_not_extended_by_use(env):
    user = await persistent(env, age=89, remaining=0.5)
    before = (await stored(env, user)).absolute_expires_at
    assert (await user.api.get("/api/v1/auth/session")).status_code == 200
    row = await stored(env, user)
    assert row.expires_at == row.absolute_expires_at == before


@pytest.mark.parametrize("expiry", ["idle", "cap", "tightened_cap", "strict_deployment"])
async def test_expired_sessions_do_not_revive_through_renewal_or_sso(env, expiry):
    user = await persistent(env, age=2)
    async with env.sessions() as db:
        row = await db.get(WebSession, user.session.id)
        if expiry == "idle":
            row.expires_at = now() - timedelta(seconds=1)
        elif expiry == "cap":
            row.absolute_expires_at = now() - timedelta(seconds=1)
        elif expiry == "tightened_cap":
            env.provider.settings.web_reauthentication_days = 1
        else:
            env.provider.settings.web_session_policy = "strict"
        await db.commit()
    response = await user.api.get("/api/v1/auth/session")
    assert response.json()["authenticated"] is False
    assert response.json()["session_expires_at"] is None
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    await user.api.get("/api/v1/auth/login")
    assert env.provider.authorization.call_args.args[3] is True
    env.provider.inspect.assert_not_awaited()


async def test_strict_and_legacy_sessions_keep_existing_deadline_after_opt_in(env):
    user = await env.client()
    env.provider.settings.web_session_policy = "persistent"
    original = user.session.expires_at
    response = await user.api.get("/api/v1/auth/session")
    assert response.json()["session_policy"] == "strict"
    assert "set-cookie" not in response.headers
    assert (await stored(env, user)).expires_at == original


async def test_new_login_takes_configured_policy_but_anonymous_does_not(env):
    user = await env.client()
    env.provider.settings.web_session_policy = "persistent"
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    await user.api.get("/api/v1/auth/login")
    state = env.provider.authorization.call_args.args[0]
    exchange_as(env, user.identity.subject)
    response = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert response.status_code == 303
    assert (await stored(env, user)).policy_mode == "persistent"
    assert "Max-Age=2592000" in response.headers["set-cookie"]
    user.api.cookies.clear()
    response = await user.api.get("/api/v1/auth/session")
    assert response.json()["authenticated"] is False
    assert "Max-Age=28800" in response.headers["set-cookie"]


@pytest.mark.parametrize(
    "code", ["server_error", "temporarily_unavailable", "invalid_client", "unauthorized_client"]
)
async def test_oauth_temporary_or_configuration_errors_keep_credentials_and_deadline(env, code):
    user = await persistent(env)
    await expire_access(env, user)
    previous = await stored(env, user)
    env.provider.refresh = AsyncMock(
        side_effect=OAuthError(error=code, description="secret-private-error")
    )
    response = await user.api.get("/api/v1/auth/session")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "identity_unavailable"
    assert "secret-private-error" not in response.text
    row = await stored(env, user)
    assert row.identity_id == previous.identity_id
    assert row.tokens == previous.tokens
    assert row.expires_at == previous.expires_at
    assert not row.requires_reauth
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("status", [429, 500, 401])
async def test_upstream_http_status_is_not_local_logout_and_retry_after_is_preserved(env, status):
    user = await persistent(env)
    req = httpx.Request("POST", "https://identity.test/token")
    upstream = httpx.Response(status, headers={"Retry-After": "3600"}, request=req)
    env.provider.inspect = AsyncMock(
        side_effect=httpx.HTTPStatusError("private", request=req, response=upstream)
    )
    before = await stored(env, user)
    response = await user.api.get("/api/v1/auth/session")
    assert response.status_code == (429 if status == 429 else 503)
    if status == 429:
        assert response.headers["Retry-After"] == "3600"
    after = await stored(env, user)
    assert (before.tokens, before.expires_at) == (after.tokens, after.expires_at)


async def test_successful_rotation_survives_subsequent_network_failure(env):
    user = await persistent(env)
    await expire_access(env, user)
    env.provider.refresh = AsyncMock(
        return_value={
            "access_token": "new",
            "refresh_token": "new-r",
            "expires_at": time.time() + 900,
        }
    )
    env.provider.inspect = AsyncMock(side_effect=httpx.ConnectError("private network"))
    assert (await user.api.get("/api/v1/auth/session")).status_code == 503
    row = await stored(env, user)
    assert env.provider.unseal(row.tokens)["refresh_token"] == "new-r"
    assert row.expires_at < now() + timedelta(days=4)
    env.provider.inspect = AsyncMock()
    assert (await user.api.get("/api/v1/auth/session")).status_code == 200
    assert env.provider.refresh.await_count == 1


async def test_refresh_is_serialized_between_tabs(env):
    user = await persistent(env)
    await expire_access(env, user)
    entered, proceed = asyncio.Event(), asyncio.Event()

    async def refresh(_token):
        entered.set()
        await proceed.wait()
        return {"access_token": "new", "refresh_token": "new-r", "expires_at": time.time() + 900}

    env.provider.refresh = AsyncMock(side_effect=refresh)
    one = asyncio.create_task(user.api.get("/api/v1/auth/session"))
    await entered.wait()
    two = asyncio.create_task(user.api.get("/api/v1/auth/session"))
    proceed.set()
    responses = await asyncio.gather(one, two)
    assert all(r.status_code == 200 for r in responses)
    assert env.provider.refresh.await_count == 1


async def test_explicit_logout_wins_over_inflight_refresh(env):
    user = await persistent(env)
    raw = user.api.cookies.get(COOKIE)
    await expire_access(env, user)
    entered, proceed = asyncio.Event(), asyncio.Event()

    async def refresh(_token):
        entered.set()
        await proceed.wait()
        return {"access_token": "new", "refresh_token": "new-r", "expires_at": time.time() + 900}

    env.provider.refresh = AsyncMock(side_effect=refresh)
    renewal = asyncio.create_task(user.api.get("/api/v1/auth/session"))
    await entered.wait()
    logout = asyncio.create_task(user.api.post("/api/v1/auth/logout"))
    proceed.set()
    assert (await renewal).status_code in {200, 401}
    assert (await logout).status_code == 200
    assert await stored(env, user) is None
    user.api.cookies.clear()
    user.api.cookies.set(COOKIE, raw, domain="127.0.0.1", path="/")
    assert not (await user.api.get("/api/v1/auth/session")).json()["authenticated"]


async def test_permanent_invalid_grant_requires_reauthentication(env):
    user = await persistent(env)
    await expire_access(env, user)
    env.provider.refresh = AsyncMock(side_effect=OAuthError(error="invalid_grant"))
    assert (await user.api.get("/api/v1/auth/session")).status_code == 401
    row = await stored(env, user)
    assert row.identity_id is None and row.tokens is None and row.requires_reauth
    assert not (await user.api.get("/api/v1/auth/session")).json()["authenticated"]
