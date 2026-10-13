"""Login resumes an internal page and isolated deployments do not share cookies."""

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from test_identity_access import env as identity_env
from test_identity_access import exchange_as

from app.modules.auth.return_to import login_return_to
from app.modules.auth.service import COOKIE

env = identity_env


@pytest.mark.parametrize(
    "target",
    [
        "/model-channels?q=hello%20world&page=2#results",
        "/models",
        "/account?tab=security",
        "/skills/01234567-89ab-cdef-0123-456789abcdef",
        "/",
        "/setup",
        "/join",
    ],
)
@pytest.mark.asyncio
async def test_login_round_trip_preserves_page(env, target):
    user = await env.client()
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    response = await user.api.get("/api/v1/auth/login", params={"next": target})
    assert response.status_code == 307
    state = env.provider.authorization.call_args.args[0]
    exchange_as(env, user.identity.subject)
    response = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert response.status_code == 303
    assert response.headers["location"] == ("/console" if target in ("/", "/setup") else target)
    assert (await user.api.get("/api/v1/auth/session")).json()["authenticated"]


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.test",
        "//evil.test",
        "/\\evil.test",
        "/%2f%2fevil.test",
        "/%252f%252fevil.test",
        "/a/../api/v1/auth/logout",
        "/api/v1/auth/logout",
        "/login?next=/models",
        "/login/",
        "/models\r\nLocation:https://evil.test",
        " /models",
        "/models\t",
        "/" + "a" * 2048,
    ],
)
def test_external_or_action_return_targets_are_rejected(target):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        login_return_to(target)
    assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_invalid_destination_never_starts_an_oidc_attempt(env):
    user = await env.client()
    env.provider.authorization = AsyncMock()
    response = await user.api.get("/api/v1/auth/login", params={"next": "//evil.test"})
    assert response.status_code == 400
    env.provider.authorization.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_login_can_retry_the_original_page(env):
    user = await env.client()
    target = "/model-channels?page=2&q=hello%20world#results"
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    await user.api.get("/api/v1/auth/login", params={"next": target})
    state = env.provider.authorization.call_args.args[0]
    response = await user.api.get(
        "/api/v1/auth/callback", params={"state": state, "error": "access_denied"}
    )
    location = urlsplit(response.headers["location"])
    assert location.path == "/login"
    assert parse_qs(location.query) == {"error": ["cancelled"], "next": [target]}


@pytest.mark.asyncio
async def test_isolated_cookie_survives_other_local_deployment_cookie_changes(env):
    user = await env.client()
    own_cookie = "actvero_newapi_acceptance_5794"
    env.provider.settings.session_cookie_name = own_cookie
    user.api.cookies.set(own_cookie, user.api.cookies.get(COOKIE))
    # A second app on the same hostname writes its own cookie. Browser ports do
    # not isolate cookies; this must not replace the acceptance session.
    user.api.cookies.set(COOKIE, "other-local-deployment-session")
    for _ in range(3):
        response = await user.api.get("/api/v1/auth/session")
        assert response.json()["authenticated"] is True
        assert response.json()["user"]["id"] == str(user.user.id)
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    await user.api.get("/api/v1/auth/login", params={"next": "/models"})
    state = env.provider.authorization.call_args.args[0]
    # It may also change while the OIDC callback is pending.
    user.api.cookies.set(COOKIE, "another-local-deployment-session")
    exchange_as(env, user.identity.subject)
    result = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert result.status_code == 303 and result.headers["location"] == "/models"
    assert own_cookie in result.headers["set-cookie"]
    assert user.api.cookies.get(COOKIE) == "another-local-deployment-session"
    assert (await user.api.get("/api/v1/auth/session")).json()["authenticated"]
    logout = await user.api.post(
        "/api/v1/auth/logout",
        headers={"x-csrf-token": (await user.api.get("/api/v1/auth/session")).json()["csrf"]},
    )
    assert logout.status_code == 200
    assert own_cookie in logout.headers["set-cookie"]
    assert not (await user.api.get("/api/v1/auth/session")).json()["authenticated"]


@pytest.mark.asyncio
async def test_custom_browser_cookie_cannot_enter_native_api(env):
    user = await env.client()
    env.provider.settings.session_cookie_name = "custom_browser_session"
    user.api.cookies.clear()
    user.api.cookies.set("custom_browser_session", "browser-cookie")
    user.api.headers.pop("origin", None)
    response = await user.api.get("/api/v1/desktop/bootstrap")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "credential_type_mismatch"


@pytest.mark.asyncio
async def test_default_login_and_duplicate_callback_keep_existing_identity(env):
    user = await env.client()
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    await user.api.get("/api/v1/auth/login")
    state = env.provider.authorization.call_args.args[0]
    exchange_as(env, user.identity.subject)
    first = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert first.headers["location"] == "/console"
    cookie = first.cookies.get(COOKIE)
    # Match browser replacement of the host cookie; the fixture starts with
    # an unscoped HTTPX cookie that otherwise coexists with the callback one.
    user.api.cookies.clear()
    user.api.cookies.set(COOKIE, cookie, domain="127.0.0.1", path="/")
    again = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert again.headers["location"].startswith("/login?error=callback")
    assert env.provider.exchange.call_count == 1
    assert user.api.cookies.get(COOKIE) == cookie
    context = (await user.api.get("/api/v1/auth/session")).json()
    assert context["authenticated"] and context["user"]["id"] == str(user.user.id)


@pytest.mark.asyncio
async def test_expired_pending_login_cannot_authenticate_anonymous_session(env):
    from datetime import timedelta

    from app.modules.auth.models import WebSession
    from app.modules.auth.service import now

    user = await env.client()
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    await user.api.get("/api/v1/auth/login", params={"next": "/model-channels"})
    state = env.provider.authorization.call_args.args[0]
    async with env.sessions() as db:
        current = await db.get(WebSession, user.session.id)
        current.identity_id = None
        current.tokens = None
        current.login_expires_at = now() - timedelta(seconds=1)
        await db.commit()
    env.provider.exchange = AsyncMock()
    response = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert response.headers["location"].startswith("/login?error=callback")
    env.provider.exchange.assert_not_called()
    assert not (await user.api.get("/api/v1/auth/session")).json()["authenticated"]
