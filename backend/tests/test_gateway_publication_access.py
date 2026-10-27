"""Publication readiness, authorization and side-effect-free member previews."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from llm_billing_helpers import billing
from pydantic import SecretStr
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_model_gateway import BASE, bind

from app.modules.llm.models import CatalogModel, ModelCall, QuotaClock, UsageSettlement
from app.modules.members.models import Membership
from app.modules.model_gateway import client
from app.modules.quota.models import QuotaPolicy

env = identity_env
pytestmark = pytest.mark.asyncio


async def setup(env, monkeypatch):
    admin = await env.client()
    bind(env, admin)
    connection = env.provider.settings.newapi_connections[0]
    connection.relay_key, connection.relay_token_id = SecretStr("fixture"), 1
    await billing(admin)
    channels = [
        {
            "id": 1,
            "name": "Fixture",
            "type": 43,
            "status": 1,
            "group": "default",
            "models": "team",
            "model_mapping": '{"team":"deepseek-flash"}',
        }
    ]
    prices = {"entries": [{"model_name": "team", "effective": {"ModelPrice": 0}}]}

    async def native(request, tenant, method, path, **kwargs):
        assert method == "GET" and tenant == admin.tenant.id
        if path == "/api/channel/":
            return {"items": channels, "total": len(channels)}
        if path == "/api/option/model_pricing":
            return prices
        raise AssertionError(path)

    call = AsyncMock(side_effect=native)
    monkeypatch.setattr(client, "call", call)
    draft = {
        "model_name": "team",
        "name": "Team model",
        "version": 0,
        "enabled": True,
        "audience": "organization",
    }
    return admin, draft, channels, prices, call


async def test_preview_and_batch_never_create_calls_models_or_quota_clocks(env, monkeypatch):
    admin, draft, _, _, call = await setup(env, monkeypatch)
    member = await env.client(role="member", tenant=admin.tenant)
    async with env.sessions() as db:
        policy = await db.scalar(
            select(QuotaPolicy).where(QuotaPolicy.tenant_id == admin.tenant.id)
        )
        policy.rules = [{"kind": "fixed_hours", "hours": 168, "points": "100"}]
        await db.commit()
    batch = await admin.api.post(BASE + "/publication/status", json={"models": ["team"]})
    assert batch.status_code == 200, batch.text
    status = batch.json()["items"][0]
    assert status["ready"] and not status["enabled"]
    assert status["active_channels"] == 1
    call.reset_mock()
    preview = await admin.api.post(
        BASE + "/publication/preview", json={"draft": draft, "member_id": str(member.member.id)}
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["discoverable"] and data["remaining_points"] == "100"
    assert data["resets_at"] is None and data["quota_status"] == "active"
    assert call.await_count == 2
    async with env.sessions() as db:
        for table in (CatalogModel, ModelCall, UsageSettlement, QuotaClock):
            assert await db.scalar(select(func.count()).select_from(table)) == 0


async def test_open_policy_is_preserved_when_channel_breaks_and_drafts_remain_editable(
    env, monkeypatch
):
    admin, draft, channels, prices, _ = await setup(env, monkeypatch)
    saved = await admin.api.put(BASE + "/publication", json=draft)
    assert saved.status_code == 200, saved.text
    version = saved.json()["data"]["version"]
    channels[0]["status"] = 2
    response = await admin.api.post(BASE + "/publication/status", json={"models": ["team"]})
    state = response.json()["items"][0]
    assert state["enabled"] and not state["ready"]
    assert next(c for c in state["checks"] if c["key"] == "channels")["status"] == "blocked"
    blocked = await admin.api.put(BASE + "/publication", json={**draft, "version": version})
    assert blocked.status_code == 409
    prices["entries"] = []
    draft.update(enabled=False, version=version)
    saved = await admin.api.put(BASE + "/publication", json=draft)
    assert saved.status_code == 200, saved.text
    assert not saved.json()["data"]["enabled"]
    assert channels[0]["status"] == 2


async def test_member_preview_enforces_membership_scope_and_current_draft(env, monkeypatch):
    admin, draft, _, _, call = await setup(env, monkeypatch)
    member = await env.client(role="member", tenant=admin.tenant)
    blocked = await member.api.post(BASE + "/publication/status", json={"models": ["team"]})
    assert blocked.status_code == 403
    foreign = await admin.api.post(
        BASE + "/publication/preview", json={"draft": draft, "member_id": str(uuid4())}
    )
    assert foreign.status_code == 404
    call.assert_not_awaited()
    payload = {"draft": {**draft, "audience": "administrators"}, "member_id": str(member.member.id)}
    response = await admin.api.post(BASE + "/publication/preview", json=payload)
    assert not response.json()["discoverable"]
    payload["draft"].update(audience="selected", member_ids=[str(member.member.id)])
    response = await admin.api.post(BASE + "/publication/preview", json=payload)
    assert response.json()["discoverable"]
    assert response.json()["quota_status"] == "active"
    async with env.sessions() as db:
        row = await db.get(Membership, member.member.id)
        row.status = "paused"
        await db.commit()
    response = await admin.api.post(BASE + "/publication/preview", json=payload)
    assert not response.json()["discoverable"]


async def test_failed_native_reads_are_unknown_not_ready_or_silently_free(env, monkeypatch):
    from fastapi import HTTPException

    admin, _, _, _, _ = await setup(env, monkeypatch)
    monkeypatch.setattr(client, "call", AsyncMock(side_effect=HTTPException(502, "unavailable")))
    response = await admin.api.post(BASE + "/publication/status", json={"models": ["team"]})
    assert response.status_code == 200
    state = response.json()["items"][0]
    assert not state["ready"]
    assert {c["key"] for c in state["checks"] if c["status"] == "unknown"} == {
        "channels",
        "pricing",
    }


async def test_empty_member_selection_does_not_report_a_model_parameter_error(env, monkeypatch):
    admin, draft, _, _, _ = await setup(env, monkeypatch)
    response = await admin.api.post(
        BASE + "/publication/preview",
        json={
            "draft": {**draft, "audience": "selected", "member_ids": []},
        },
    )
    assert response.status_code == 200, response.text
    checks = {c["key"]: c for c in response.json()["configuration"]["checks"]}
    assert checks["parameters"]["status"] == "ready"
    assert checks["members"]["status"] == "blocked"
