"""Portal policy is public data; its mutation remains deployment-scoped."""

from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import func, select, text
from test_identity_access import env  # noqa: F401
from test_platform_settings import operator

from app.modules.auth.models import WebSession
from app.modules.tenants.models import Installation, PlatformOperator

pytestmark = pytest.mark.asyncio
PUBLIC = "/api/v1/platform/site"
PRIVATE = "/api/v1/platform/portal"


async def test_public_default_does_not_authenticate_create_sessions_or_expose_private_settings(env):  # noqa: F811
    async with env.sessions() as db:
        before = await db.scalar(select(func.count()).select_from(WebSession))
    env.provider.inspect.side_effect = RuntimeError("identity offline")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url=env.provider.settings.app_url
    ) as public:
        response = await public.get(PUBLIC)
        assert response.status_code == 200
        assert response.json() == {"portal_enabled": False}
        assert response.headers["Cache-Control"] == "no-store"
        assert "set-cookie" not in response.headers
        assert (await public.put(PRIVATE, json={"portal_enabled": True})).status_code == 403
    env.provider.inspect.assert_not_awaited()
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(WebSession)) == before


async def test_portal_roundtrip_preserves_brand_identity_and_desktop_metadata(env):  # noqa: F811
    actor = await operator(env)
    assert (await actor.api.get(PRIVATE)).json() == {"portal_enabled": False}
    async with env.sessions() as db:
        before = (await db.execute(text("SELECT to_jsonb(i) FROM installation i"))).scalar_one()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url=env.provider.settings.app_url
    ) as public:
        metadata = await public.get("/api/v1/desktop/metadata")
        for enabled in (True, False):
            response = await actor.api.put(PRIVATE, json={"portal_enabled": enabled})
            assert response.status_code == 200
            assert response.json() == {"portal_enabled": enabled}
            assert (await public.get(PUBLIC)).json() == response.json()
            assert (await actor.api.get(PRIVATE)).json() == response.json()
            async with env.sessions() as db:
                after = (
                    await db.execute(text("SELECT to_jsonb(i) FROM installation i"))
                ).scalar_one()
                assert after.pop("portal_enabled") is enabled
                assert after == {k: v for k, v in before.items() if k != "portal_enabled"}
            unchanged = await public.get("/api/v1/desktop/metadata")
            assert unchanged.json() == metadata.json()
            assert unchanged.headers["ETag"] == metadata.headers["ETag"]


async def test_portal_requires_platform_operator_and_mutation_csrf(env):  # noqa: F811
    actor = await operator(env)
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    for other in (admin, member):
        assert (await other.api.get(PRIVATE)).status_code == 403
        assert (await other.api.put(PRIVATE, json={"portal_enabled": True})).status_code == 403
    for headers in ({"x-csrf-token": "wrong"}, {"origin": "https://foreign.example"}):
        assert (
            await actor.api.put(PRIVATE, json={"portal_enabled": True}, headers=headers)
        ).status_code == 403
    async with env.sessions() as db:
        operator_record = await db.get(PlatformOperator, actor.user.id)
        operator_record.status = "paused"
        await db.commit()
    assert (await actor.api.get(PRIVATE)).status_code == 403
    assert (await actor.api.put(PRIVATE, json={"portal_enabled": True})).status_code == 403
    assert (await actor.api.get(PUBLIC)).json() == {"portal_enabled": False}


@pytest.mark.parametrize("value", [None, "false", "true", 0, 1, [], {}])
async def test_portal_accepts_only_explicit_boolean(env, value):  # noqa: F811
    actor = await operator(env)
    assert (await actor.api.put(PRIVATE, json={"portal_enabled": value})).status_code == 422
    assert (await actor.api.get(PRIVATE)).json() == {"portal_enabled": False}


async def test_missing_or_extra_fields_cannot_modify_other_settings(env):  # noqa: F811
    actor = await operator(env)
    for payload in ({}, {"portal_enabled": True, "platform_name": "injected"}):
        assert (await actor.api.put(PRIVATE, json=payload)).status_code == 422
    await actor.api.put(PRIVATE, json={"portal_enabled": True})
    await actor.api.put("/api/v1/platform/settings", json={"platform_name": "Brand"})
    assert (await actor.api.get(PRIVATE)).json() == {"portal_enabled": True}
    async with env.sessions() as db:
        install = await db.get(Installation, 1)
        assert install.platform_name == "Brand" and install.portal_enabled is True


@pytest.mark.parametrize("enabled", [False, True])
async def test_portal_does_not_gate_platform_mail_registration_or_downloads(env, enabled):  # noqa: F811
    actor = await operator(env)
    paths = [
        "/api/v1/platform/settings",
        "/api/v1/platform/registration",
        "/api/v1/platform/mail",
        "/api/v1/platform/mail/preview?template=organization_invitation",
        "/api/v1/platform/mail/preview?template=member_invitation",
        "/api/v1/platform/organizations",
        "/api/v1/platform/organization-invitations",
        "/api/v1/platform/applications",
        "/api/v1/platform/downloads",
        "/api/v1/platform/downloads/public",
    ]
    before = {}
    for path in paths:
        response = await actor.api.get(path)
        assert response.status_code == 200, (path, response.text)
        before[path] = response.json()
    assert (await actor.api.put(PRIVATE, json={"portal_enabled": enabled})).status_code == 200
    for path in paths:
        response = await actor.api.get(path)
        assert response.status_code == 200, (path, response.text)
        assert response.json() == before[path]
    # Ordinary setting mutations remain possible under either homepage policy.
    changed = await actor.api.put("/api/v1/platform/settings", json={"platform_name": "独立设置"})
    assert changed.status_code == 200
    assert changed.json()["platform_name"] == "独立设置"
    assert (await actor.api.get(PRIVATE)).json() == {"portal_enabled": enabled}


@pytest.mark.parametrize("enabled", [False, True])
async def test_portal_does_not_gate_anonymous_login_or_self_service_registration(env, enabled):  # noqa: F811
    actor = await operator(env)
    async with env.sessions() as db:
        install = await db.get(Installation, 1)
        install.platform_operator_user_id = actor.user.id
        await db.commit()
    assert (
        await actor.api.put("/api/v1/platform/registration", json={"mode": "self_service"})
    ).status_code == 200
    assert (await actor.api.put(PRIVATE, json={"portal_enabled": enabled})).status_code == 200
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url=env.provider.settings.app_url
    ) as public:
        session = (await public.get("/api/v1/auth/session")).json()
        assert session["authenticated"] is False
        assert session["setup_complete"] is True
        assert session["registration_mode"] == "self_service"
        opening = await public.get("/api/v1/organization-onboarding/current")
        assert opening.status_code == 200
        assert opening.json()["state"] == "form"
        assert opening.json()["mode"] == "self_service"
        env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
        login = await public.get("/api/v1/auth/login?next=%2Fconsole")
        assert login.status_code == 307
        assert login.headers["location"] == "https://identity.test/login"
        env.provider.authorization.assert_awaited_once()
