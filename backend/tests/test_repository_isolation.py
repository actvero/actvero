"""Merged gateway isolation: two organizations in one real PostgreSQL schema."""

from uuid import UUID, uuid4

import pytest
from llm_billing_helpers import billing
from sqlalchemy import select, text
from test_access_keys import create as create_key
from test_access_keys import (
    headers,
    identity,  # noqa: F401 -- native identity test double
)
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_execution import GATEWAY, configured, entries, payload, upstream
from test_mcp import listening

from app.modules.auth.models import WebSession
from app.modules.experts.categories import seed_categories as expert_categories
from app.modules.llm.models import CatalogModel, ModelCall, ModelChannel, MutationReceipt
from app.modules.skills.categories import seed_categories as skill_categories
from app.modules.tenants.models import PlatformOperator, Tenant

env = identity_env
pytestmark = pytest.mark.asyncio


async def organizations(env):
    env.provider.settings.platform_edition = "saas"
    first = await env.client()
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        tenant = Tenant(name="Second organization")
        db.add(tenant)
        await db.flush()
        expert_categories(db, tenant.id)
        skill_categories(db, tenant.id)
        await db.commit()
    second = await env.client(tenant=tenant)
    async with env.sessions() as db:
        for actor in (first, second):
            session = await db.get(WebSession, actor.session.id)
            session.tenant_id = actor.tenant.id
        await db.commit()
    return first, second


async def test_resources_receipts_and_foreign_binding_are_tenant_scoped(env):
    first, second = await organizations(env)
    request_id = str(uuid4())
    body = dict(
        request_id=request_id,
        name="Same channel",
        base_url="https://example.test/v1",
        auth_mode="none",
    )
    rows = []
    for admin in [first, second]:
        result = await admin.api.post("/api/v1/llm/channels", json=body)
        assert result.status_code == 200, result.text
        rows.append(result.json())
        replay = await admin.api.post("/api/v1/llm/channels", json=body)
        assert replay.json()["id"] == result.json()["id"]
    assert rows[0]["id"] != rows[1]["id"]
    for admin, foreign in [(first, rows[1]), (second, rows[0])]:
        base = "/api/v1/llm/channels/" + foreign["id"]
        assert (await admin.api.get(base)).status_code == 404
        assert (await admin.api.get(base + "/tests")).status_code == 404
        assert (
            await admin.api.put(base + "/archive", json={"version": 1, "archived": True})
        ).status_code == 404
        bad = await admin.api.post(
            "/api/v1/llm/models",
            json={
                "slug": "same-model",
                "name": "Same model",
                "bindings": [{"channel_id": foreign["id"], "upstream_id": "not-registered"}],
            },
        )
        assert bad.status_code == 422, bad.text
        own = await admin.api.post(
            "/api/v1/llm/models", json={"slug": "same-model", "name": "Same model"}
        )
        assert own.status_code == 200, own.text
    async with env.sessions() as db:
        receipts = list(await db.scalars(select(MutationReceipt)))
        channels = list(await db.scalars(select(ModelChannel)))
        models = list(await db.scalars(select(CatalogModel)))
        assert len(receipts) == len(channels) == len(models) == 2
        assert {r.tenant_id for r in receipts} == {first.tenant.id, second.tenant.id}
        assert (await second.api.get("/api/v1/llm/models/" + str(models[0].id))).status_code == (
            404 if models[0].tenant_id == first.tenant.id else 200
        )


async def test_same_client_idempotency_key_has_independent_usage_and_quota(env):
    first, second = await organizations(env)
    await billing(first, points="0.281")
    await billing(second, points="100")
    app, state = upstream()
    async with listening(app) as base:
        left, _ = await configured(env, first, base)
        right, _ = await configured(env, second, base)
        key_left, _ = await create_key(first)
        key_right, _ = await create_key(second)
        async with native_client(env) as api:
            for model, key in [(left, key_left), (right, key_right)]:
                result = await api.post(
                    GATEWAY,
                    headers={**headers(key), "Idempotency-Key": "same-request"},
                    json=payload(model),
                )
                assert result.status_code == 200, result.text
                replay = await api.post(
                    GATEWAY,
                    headers={**headers(key), "Idempotency-Key": "same-request"},
                    json=payload(model),
                )
                assert replay.status_code == 409, replay.text
            assert len(state["calls"]) == 2
            blocked = await api.post(GATEWAY, headers=headers(key_left), json=payload(left))
            assert blocked.status_code == 429, blocked.text
            allowed = await api.post(GATEWAY, headers=headers(key_right), json=payload(right))
            assert allowed.status_code == 200, allowed.text
            assert len(state["calls"]) == 3
            own_left, own_right = await entries(first), await entries(second)
            assert len(own_left) == 1 and len(own_right) == 2
            assert own_left[0]["id"] != own_right[0]["id"]
            call = own_left[0]["id"]
            assert (await second.api.get("/api/v1/llm/calls/" + call)).status_code == 404
            assert (
                await second.api.post(
                    "/api/v1/llm/settlements/" + call + "/reconcile",
                    json={"version": 1, "action": "release", "reason": "foreign"},
                )
            ).status_code == 404
            operator = await env.client(joined=False)
            async with env.sessions() as db:
                db.add(PlatformOperator(user_id=operator.user.id))
                await db.commit()
            assert (await operator.api.get("/api/v1/llm/channels")).status_code == 403
            assert (
                await operator.api.post(
                    "/api/v1/account/access-keys",
                    json={"creation_id": str(uuid4()), "name": "No implicit privileges"},
                )
            ).status_code == 403
    async with env.sessions() as db:
        calls = list(await db.scalars(select(ModelCall)))
        assert {c.tenant_id for c in calls} == {first.tenant.id, second.tenant.id}
        for call in calls:
            assert (await db.get(CatalogModel, call.model_id)).tenant_id == call.tenant_id
        assert (await db.get(CatalogModel, UUID(left["id"]))).slug == right["slug"]
