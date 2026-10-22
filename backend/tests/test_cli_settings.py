"""Platform-only CLI policy controls all management authentication paths live."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text
from test_identity_access import env  # noqa: F401
from test_management_cli import bearer, login
from test_platform_settings import operator

from app.modules.desktop.oidc import NativeIdentity
from app.modules.tenants.models import Installation, PlatformOperator

pytestmark = pytest.mark.asyncio
PATH = "/api/v1/platform/cli"
BASE = "/api/v1/management"


@pytest.mark.parametrize("default", [False, True])
async def test_default_is_preserved_and_saved_choice_controls_new_requests(env, default):  # noqa: F811
    actor = await operator(env)
    env.provider.settings.management_enabled = default
    response = await actor.api.get(PATH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "enabled": default,
        "source": "environment",
        "server_url": env.provider.settings.app_url,
        "client_id": "actvero-cli",
        "issuer": env.provider.settings.oidc_issuer,
    }
    async with env.sessions() as db:
        before = (await db.execute(text("SELECT to_jsonb(i) FROM installation i"))).scalar_one()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as api:
        for enabled in (True, False, True):
            saved = await actor.api.put(PATH, json={"enabled": enabled})
            assert saved.status_code == 200
            assert saved.json()["enabled"] is enabled
            assert saved.json()["source"] == "platform"
            # A deployment-default change cannot undo the persisted platform choice.
            env.provider.settings.management_enabled = not enabled
            assert (await actor.api.get(PATH)).json() == saved.json()
            metadata = await api.get(BASE + "/metadata")
            assert metadata.status_code == (200 if enabled else 503)
            if enabled:
                assert metadata.json()["resource_contract_version"] == 1
            else:
                assert metadata.json()["error"]["code"] == "management_disabled"
            async with env.sessions() as db:
                after = (
                    await db.execute(text("SELECT to_jsonb(i) FROM installation i"))
                ).scalar_one()
                assert after.pop("management_enabled") is enabled
                assert after == {k: v for k, v in before.items() if k != "management_enabled"}


async def test_platform_authority_csrf_and_no_implicit_organization_access(env, monkeypatch):  # noqa: F811
    admin = await env.client()
    assert (await admin.api.get(PATH)).status_code == 404
    actor = await operator(env)
    member = await env.client(role="member", tenant=admin.tenant)
    for other in (admin, member):
        assert (await other.api.get(PATH)).status_code == 403
        assert (await other.api.put(PATH, json={"enabled": True})).status_code == 403
    for headers in ({"x-csrf-token": "wrong"}, {"origin": "https://foreign.example"}):
        assert (
            await actor.api.put(PATH, json={"enabled": True}, headers=headers)
        ).status_code == 403
    assert (await actor.api.put(PATH, json={"enabled": True})).status_code == 200
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as api:
        tokens, _ = await login(env, monkeypatch, api, actor)
        response = await api.get(
            f"{BASE}/organizations/{admin.tenant.id}/skills", headers=bearer(tokens)
        )
        assert response.status_code == 403
        assert (await api.get(PATH)).status_code == 401
        assert (await api.get(PATH, headers=bearer(tokens))).status_code == 401
    async with env.sessions() as db:
        row = await db.get(PlatformOperator, actor.user.id)
        row.status = "paused"
        await db.commit()
    assert (await actor.api.get(PATH)).status_code == 403
    assert (await actor.api.put(PATH, json={"enabled": False})).status_code == 403


async def test_disable_blocks_credentials_resources_and_oauth(env, monkeypatch):  # noqa: F811
    web = await env.client()
    actor = await operator(env)
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    await actor.api.put(PATH, json={"enabled": True})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as api:
        tokens, proof = await login(env, monkeypatch, api, web)
        assert (await api.get(BASE + "/me", headers=bearer(tokens))).status_code == 200
        await actor.api.put(PATH, json={"enabled": False})
        results = [
            await api.get(BASE + "/me", headers=bearer(tokens)),
            await api.get(f"{BASE}/organizations/{web.tenant.id}/skills", headers=bearer(tokens)),
            await api.post(BASE + "/login/exchange", json=proof),
            await api.post(
                BASE + "/refresh",
                json={
                    "refresh_token": tokens["refresh_token"],
                    "request_id": str(uuid4()),
                },
            ),
            await api.get(BASE + "/mcp/oauth/callback?state=invalid&code=invalid"),
        ]
        for response in results:
            assert response.status_code == 503, response.text
            assert response.json()["error"]["code"] == "management_disabled"
        # Pausing access does not silently revoke otherwise-valid sessions.
        await actor.api.put(PATH, json={"enabled": True})
        assert (await api.get(BASE + "/me", headers=bearer(tokens))).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"enabled": None},
        {"enabled": "true"},
        {"enabled": 1},
        {"enabled": True, "client_id": "other"},
    ],
)
async def test_accepts_only_explicit_boolean_and_no_identity_settings(env, payload):  # noqa: F811
    actor = await operator(env)
    assert (await actor.api.put(PATH, json=payload)).status_code == 422
    async with env.sessions() as db:
        assert await db.scalar(select(Installation.management_enabled)) is None
