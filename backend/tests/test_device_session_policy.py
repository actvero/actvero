"""Persistent recovery, crash-safe rotation and fixed organization authority."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx2
import pytest
from sqlalchemy import text
from test_desktop import bearer, login, native_client
from test_desktop_mcp import token
from test_identity_access import env as identity_env

from app.modules.auth.service import digest, now
from app.modules.desktop import router, service
from app.modules.desktop.models import DeviceSession, DeviceToken
from app.modules.desktop.oidc import NativeIdentity
from app.modules.members.models import Membership
from app.modules.tenants.models import Tenant

env = identity_env
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


def stamp(monkeypatch, when):
    monkeypatch.setattr(router, "now", lambda: when)
    monkeypatch.setattr(service, "now", lambda: when)


async def rotate(api, root, version=2, request_id=None):
    body = {
        "refresh_token": root["refresh_token"],
        "request_id": str(request_id or uuid4()),
        "recovery_version": version,
    }
    response = await api.post("/api/v1/desktop/refresh", json=body)
    return body, response


async def test_persistent_offline_window_and_successful_refresh_rolls(env, monkeypatch):
    env.provider.settings.desktop_session_policy = "persistent"
    web = await env.client()
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, web)
        start = now()
        assert root["session_policy"] == "persistent"
        assert root["reauthenticate_at"] is None
        stamp(monkeypatch, start + timedelta(days=2))
        _, response = await rotate(api, root)
        assert response.status_code == 200, response.text
        result = response.json()
        assert datetime.fromisoformat(result["session_expires_at"]) > start + timedelta(days=31)
        assert (await api.get("/api/v1/desktop/me", headers=bearer(result))).status_code == 200
        async with env.sessions() as db:
            row = await db.get(DeviceSession, UUID(root["device_session_id"]))
            assert (
                row.idle_expires_at == row.expires_at
            )  # Business activity never restores 60m idle.
        stamp(monkeypatch, start + timedelta(days=33))
        _, expired = await rotate(api, result)
        assert expired.status_code == 401
        assert expired.json()["error"]["code"] == "session_expired"


async def test_unconfirmed_result_survives_crash_across_days_until_successor_consumed(
    env, monkeypatch
):
    env.provider.settings.desktop_session_policy = "persistent"
    web = await env.client()
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, web)
        body, response = await rotate(api, root)
        result = response.json()
        assert result["acknowledgement_required"] is True
        stamp(monkeypatch, now() + timedelta(days=2))
        async with native_client(env) as restarted:
            recovered = await restarted.post("/api/v1/desktop/refresh", json=body)
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["refresh_token"] == result["refresh_token"]
            assert recovered.json()["access_token"] == result["access_token"]
            assert recovered.json()["expires_in"] == 0
            _, renewed = await rotate(restarted, recovered.json())
            assert renewed.status_code == 200
        replay = await api.post("/api/v1/desktop/refresh", json=body)
        assert replay.status_code == 409
        async with env.sessions() as db:
            old = await db.get(DeviceToken, digest(root["refresh_token"]))
            assert old.response is None and old.acknowledged_at is not None


async def test_confirmation_is_proof_bound_idempotent_and_does_not_renew(env, monkeypatch):
    env.provider.settings.desktop_session_policy = "persistent"
    web = await env.client()
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, web)
        body, response = await rotate(api, root)
        result = response.json()
        ack = {"refresh_token": result["refresh_token"], "request_id": body["request_id"]}
        mismatch = await api.post(
            "/api/v1/desktop/refresh/acknowledge", json={**ack, "request_id": str(uuid4())}
        )
        assert mismatch.status_code == 409
        for _ in range(2):
            assert (
                await api.post("/api/v1/desktop/refresh/acknowledge", json=ack)
            ).status_code == 200
        assert (await api.post("/api/v1/desktop/refresh", json=body)).status_code == 409
        async with env.sessions() as db:
            row = await db.get(DeviceSession, UUID(root["device_session_id"]))
            assert row.expires_at == datetime.fromisoformat(result["session_expires_at"])
        assert (await api.get("/api/v1/desktop/me", headers=bearer(result))).status_code == 200
        await api.post("/api/v1/desktop/logout", json={"refresh_token": root["refresh_token"]})
        assert (await api.post("/api/v1/desktop/refresh/acknowledge", json=ack)).status_code == 401


@pytest.mark.parametrize("version,seconds", [(1, 121), (2, 7 * 86400 + 1)])
async def test_recovery_deadline_is_bounded_for_both_contracts(env, monkeypatch, version, seconds):
    env.provider.settings.desktop_session_policy = "persistent"
    web = await env.client()
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, web)
        body, response = await rotate(api, root, version)
        assert response.status_code == 200
        stamp(monkeypatch, now() + timedelta(seconds=seconds))
        expired = await api.post("/api/v1/desktop/refresh", json=body)
        assert expired.status_code == 409
        assert expired.json()["error"]["code"] == "refresh_recovery_expired"


async def test_same_request_concurrent_one_chain_other_request_cannot_steal(env, monkeypatch):
    env.provider.settings.desktop_session_policy = "persistent"
    web = await env.client()
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, web)
        body = {
            "refresh_token": root["refresh_token"],
            "request_id": str(uuid4()),
            "recovery_version": 2,
        }
        results = await asyncio.gather(
            *[api.post("/api/v1/desktop/refresh", json=body) for _ in range(3)]
        )
        assert all(r.status_code == 200 for r in results)
        assert len({r.json()["refresh_token"] for r in results}) == 1
        assert (
            await api.post("/api/v1/desktop/refresh", json={**body, "request_id": str(uuid4())})
        ).status_code == 409
        assert (
            await api.get("/api/v1/desktop/me", headers=bearer(results[0].json()))
        ).status_code == 200


async def test_temporary_identity_failure_preserves_unused_refresh(env, monkeypatch):
    env.provider.settings.desktop_session_policy = "persistent"
    web = await env.client()
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, web)
        monkeypatch.setattr(
            NativeIdentity,
            "account_valid",
            AsyncMock(side_effect=httpx2.ConnectError("private-error")),
        )
        body, failed = await rotate(api, root)
        assert failed.status_code == 503 and "private-error" not in failed.text
        async with env.sessions() as db:
            row = await db.get(DeviceToken, digest(root["refresh_token"]))
            assert row.used_at is None
        monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
        assert (await api.post("/api/v1/desktop/refresh", json=body)).status_code == 200


async def test_legacy_strict_not_promoted_and_current_strict_tightens_persistent(env, monkeypatch):
    web = await env.client()
    async with native_client(env) as api:
        legacy, _ = await login(env, monkeypatch, api, web)
        env.provider.settings.desktop_session_policy = "persistent"
        fresh, _ = await login(env, monkeypatch, api, web)
        stamp(monkeypatch, now() + timedelta(hours=9))
        assert (await rotate(api, legacy))[1].status_code == 401
        assert (await rotate(api, fresh))[1].status_code == 200
        env.provider.settings.desktop_session_policy = "strict"
        assert (await rotate(api, fresh))[1].status_code == 401


async def test_absolute_deadline_and_tightened_cap_never_extended(env, monkeypatch):
    env.provider.settings.desktop_session_policy = "persistent"
    env.provider.settings.desktop_reauthentication_days = 40
    web = await env.client()
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, web)
        start = now()
        stamp(monkeypatch, start + timedelta(days=20))
        _, response = await rotate(api, root)
        result = response.json()
        assert datetime.fromisoformat(result["session_expires_at"]) == datetime.fromisoformat(
            root["reauthenticate_at"]
        )
        env.provider.settings.desktop_reauthentication_days = 30
        stamp(monkeypatch, start + timedelta(days=31))
        assert (await rotate(api, result))[1].status_code == 401


async def test_multi_org_explicit_selection_existing_resource_stays_original(env, monkeypatch):
    env.provider.settings.platform_edition = "saas"
    web = await env.client()
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        other = Tenant(id=uuid4(), name="Second organization")
        db.add(other)
        await db.flush()
        member = Membership(
            tenant_id=other.id,
            user_id=web.user.id,
            role="member",
            source="invited",
            status="active",
        )
        db.add(member)
        await db.commit()
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, web)
        me = (await api.get("/api/v1/desktop/me", headers=bearer(root))).json()
        assert me["organization"] is None and me["organization_state"] == "selection_required"
        assert len(me["organizations"]) == 2
        rejected = await api.post(
            "/api/v1/desktop/resource-tokens",
            headers=bearer(root),
            json={"resource": "llm:catalog"},
        )
        assert (
            rejected.status_code == 403
            and rejected.json()["error"]["code"] == "organization_selection_required"
        )

        def choose(ident):
            return api.post(
                "/api/v1/desktop/organization", headers=bearer(root), json={"tenant_id": str(ident)}
            )

        assert (await choose(uuid4())).status_code == 403
        assert (await choose(web.tenant.id)).status_code == 200
        old = await token(api, root, "llm:catalog")
        old_skills = await token(api, root, "skills:catalog")
        selected = await choose(other.id)
        assert selected.json()["organization"]["tenant_id"] == str(other.id)
        new = await token(api, root, "llm:catalog")
        assert (await api.get("/api/llm/v1/models", headers=bearer(old))).status_code == 200
        assert (await api.get("/api/llm/v1/models", headers=bearer(new))).status_code == 200
        async with env.sessions() as db:
            from app.modules.desktop_mcp.models import ResourceToken

            original = await db.get(ResourceToken, digest(old["access_token"]))
            updated = await db.get(ResourceToken, digest(new["access_token"]))
            assert original.member_id == web.member.id and updated.member_id == member.id
            first = await db.get(Membership, web.member.id)
            first.status = "paused"
            first.revoked_at = now()
            await db.commit()
        assert (await api.get("/api/llm/v1/models", headers=bearer(old))).status_code == 403
        assert (
            await api.get("/api/v1/desktop/skills", headers=bearer(old_skills))
        ).status_code == 403
        assert (await api.get("/api/llm/v1/models", headers=bearer(new))).status_code == 200
        assert (await api.get("/api/v1/desktop/me", headers=bearer(root))).status_code == 200
        assert (await rotate(api, root))[1].status_code == 200
        assert (await choose(web.tenant.id)).status_code == 403
