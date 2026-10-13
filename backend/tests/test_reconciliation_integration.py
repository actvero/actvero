"""G6-02 reconciliation API/receipt behavior on isolated PostgreSQL.

These tests seed plausible historical review rows, then use the real HTTP API,
transactional ledger, audit and receipt tables. They never mock settlement.complete.
"""

import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from llm_billing_helpers import billing
from sqlalchemy import func, select
from test_channel_health import catalog, channel
from test_identity_access import env as identity_env

from app.modules.audit.models import AuditEvent
from app.modules.auth.service import now
from app.modules.llm.catalog_schemas import TokenPrice
from app.modules.llm.models import (
    CatalogModel,
    ModelCall,
    MutationReceipt,
    PointConversion,
    UsageSettlement,
)
from app.modules.members.models import Membership

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/settlements/"


async def seed_review(env, admin, member, *, price: dict, status="review", age_minutes=11):
    """A historical call with a genuine persisted price/ratio/policy snapshot."""
    async with env.sessions() as db:
        conversion = await db.scalar(
            select(PointConversion)
            .where(PointConversion.tenant_id == admin.tenant.id)
            .order_by(PointConversion.version.desc())
        )
        assert conversion is not None
        upstream = channel(admin.tenant.id)
        model, config = catalog(admin.tenant.id, [upstream], mode="fixed")
        db.add_all([upstream, model])
        await db.flush()
        call = ModelCall(
            id=uuid4(),
            tenant_id=admin.tenant.id,
            model_id=model.id,
            channel_id=upstream.id,
            actor_id=member.user.id,
            source="desktop",
            kind={
                "tokens": "chat",
                "characters": "embedding",
                "search_units": "rerank",
                "images": "image_generation",
            }[price["metric"]],
            status="unknown",
            attempts=[{"number": 1, "status": "unknown", "sent": True}],
            usage={},
        )
        db.add(call)
        await db.flush()
        row = UsageSettlement(
            id=call.id,
            tenant_id=admin.tenant.id,
            member_id=member.member.id,
            currency="USD",
            conversion_id=conversion.id,
            ratio=Decimal("37"),
            reserved_amount=Decimal("0.5"),
            price=TokenPrice.model_validate(price).model_dump(mode="json"),
            policy_snapshot={
                "status": "active",
                "policy": {"id": "historic", "version": 1},
                "windows": [],
            },
            usage={},
            status=status,
            version=1,
            created_at=now() - timedelta(minutes=age_minutes),
        )
        db.add(row)
        await db.commit()
        return call.id, model.id, config


def tagged(metric, value=1):
    if metric == "tokens":
        return {"metric": "tokens", "input_tokens": value, "output_tokens": 0}
    return {
        "metric": metric,
        {
            "characters": "input_characters",
            "search_units": "search_units",
            "images": "image_count",
        }[metric]: value,
    }


@pytest.mark.parametrize(
    "metric,price,usage,amount",
    [
        (
            "tokens",
            {
                "currency": "USD",
                "metric": "tokens",
                "input": "1",
                "output": "2",
                "cache_read": "0.5",
            },
            {
                "metric": "tokens",
                "input_tokens": 1000000,
                "output_tokens": 500000,
                "cache_read_tokens": 100000,
            },
            "2.05",
        ),
        (
            "characters",
            {"currency": "USD", "metric": "characters", "input": "1"},
            {"metric": "characters", "input_characters": 1000000},
            "1",
        ),
        (
            "search_units",
            {"currency": "USD", "metric": "search_units", "input": "1"},
            {"metric": "search_units", "search_units": 1000000},
            "1",
        ),
        (
            "images",
            {"currency": "USD", "metric": "images", "unit": 1, "input": "3"},
            {"metric": "images", "image_count": 2},
            "6",
        ),
    ],
)
async def test_preview_uses_historical_metric_price_and_ratio_after_current_edits(
    env, metric, price, usage, amount
):
    admin = await env.client()
    await billing(admin)
    call_id, model_id, _ = await seed_review(env, admin, admin, price=price)
    detail = await admin.api.get(BASE + str(call_id) + "/reconciliation")
    assert detail.status_code == 200, detail.text
    assert detail.json()["ratio"] == "37"
    assert detail.json()["price"]["metric"] == metric
    assert detail.json()["eligible"] is True
    async with env.sessions() as db:
        model = await db.get(CatalogModel, model_id)
        model.configuration = {
            **model.configuration,
            "budget_price": {"currency": "USD", "metric": metric, "input": "999"},
        }
        model.version += 1
        await db.commit()
    conversion = await admin.api.put(
        "/api/v1/llm/point-conversion",
        json={"version": 1, "currency": "USD", "points_per_currency": "200"},
    )
    assert conversion.status_code == 200, conversion.text
    preview = await admin.api.post(
        BASE + str(call_id) + "/reconcile/preview",
        json={
            "version": 1,
            "action": "settle",
            "usage": usage,
            "reason": "Vendor statement confirms the measured units",
        },
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["metric"] == metric
    assert Decimal(data["amount"]) == Decimal(amount)
    assert Decimal(data["points"]) == Decimal(amount) * Decimal("37")
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, call_id)
        assert row.status == "review" and row.version == 1 and row.amount is None


async def test_same_request_id_commits_once_and_other_payload_conflicts(env):
    admin = await env.client()
    await billing(admin)
    call_id, _, _ = await seed_review(
        env,
        admin,
        admin,
        price={"currency": "USD", "metric": "tokens", "input": "1", "output": "2"},
    )
    request_id = uuid4()
    body = {
        "version": 1,
        "request_id": str(request_id),
        "action": "settle",
        "usage": tagged("tokens", 1000000),
        "reason": "Verified vendor statement",
    }
    path = BASE + str(call_id) + "/reconcile"
    responses = await asyncio.gather(
        admin.api.post(path, json=body), admin.api.post(path, json=body)
    )
    assert [r.status_code for r in responses] == [200, 200], [r.text for r in responses]
    assert responses[0].json() == responses[1].json()
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, call_id)
        assert row.status == "settled" and row.version == 2
        assert row.amount == Decimal("1")
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.action == "llm.settlement.reconcile",
                    AuditEvent.target_id == call_id,
                )
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(MutationReceipt)
                .where(
                    MutationReceipt.scope == "settlement.reconcile",
                    MutationReceipt.request_id == request_id,
                )
            )
            == 1
        )
    changed = await admin.api.post(path, json={**body, "reason": "Different statement"})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "request_id_conflict"


async def test_input_only_token_price_with_cache_requires_and_charges_explicit_count(env):
    admin = await env.client()
    await billing(admin)
    call_id, _, _ = await seed_review(
        env,
        admin,
        admin,
        price={
            "currency": "USD",
            "metric": "tokens",
            "input": "1",
            "cache_read": "2",
        },
    )
    path = BASE + str(call_id)
    context = await admin.api.get(path + "/reconciliation")
    assert context.status_code == 200, context.text
    assert context.json()["eligible"] is True
    assert context.json()["required_fields"] == ["input_tokens", "cache_read_tokens"]
    body = {
        "version": 1,
        "request_id": str(uuid4()),
        "action": "settle",
        "usage": {"metric": "tokens", "input_tokens": 100, "cache_read_tokens": 50},
        "reason": "Verified input and cache units on the historical statement",
    }
    missing_cache = await admin.api.post(
        path + "/reconcile/preview",
        json={**body, "usage": {"metric": "tokens", "input_tokens": 100}},
    )
    assert missing_cache.status_code == 422, missing_cache.text
    preview = await admin.api.post(path + "/reconcile/preview", json=body)
    assert preview.status_code == 200, preview.text
    assert Decimal(preview.json()["amount"]) == Decimal("0.0002")
    assert Decimal(preview.json()["points"]) == Decimal("0.0074")
    committed = await admin.api.post(path + "/reconcile", json=body)
    assert committed.status_code == 200, committed.text
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, call_id)
        assert row.status == "settled" and row.version == 2
        assert row.amount == Decimal("0.0002")
        assert row.usage == {"input_tokens": 100, "cache_read_tokens": 50}


async def test_different_administrators_and_ids_compete_for_one_settlement(env):
    admin = await env.client()
    other = await env.client(tenant=admin.tenant)
    await billing(admin)
    call_id, _, _ = await seed_review(
        env,
        admin,
        admin,
        price={"currency": "USD", "metric": "characters", "input": "1"},
    )
    first_id, second_id = uuid4(), uuid4()
    path = BASE + str(call_id) + "/reconcile"
    body = {
        "version": 1,
        "action": "settle",
        "usage": tagged("characters", 1000000),
        "reason": "Verified statement for this call",
    }
    responses = await asyncio.gather(
        admin.api.post(path, json={**body, "request_id": str(first_id)}),
        other.api.post(path, json={**body, "request_id": str(second_id)}),
    )
    assert sorted(response.status_code for response in responses) == [200, 409], [
        response.text for response in responses
    ]
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, call_id)
        assert row.status == "settled" and row.version == 2
        assert row.amount == Decimal("1")
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.action == "llm.settlement.reconcile",
                    AuditEvent.target_id == call_id,
                )
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(MutationReceipt)
                .where(
                    MutationReceipt.scope == "settlement.reconcile",
                    MutationReceipt.request_id.in_([first_id, second_id]),
                )
            )
            == 1
        )


async def test_receipt_is_actor_scoped_and_restores_committed_lost_response(env):
    admin = await env.client()
    other = await env.client(tenant=admin.tenant)
    member = await env.client(role="member", tenant=admin.tenant)
    await billing(admin)
    call_id, _, _ = await seed_review(
        env,
        admin,
        admin,
        price={"currency": "USD", "metric": "images", "unit": 1, "input": "3"},
    )
    request_id = uuid4()
    body = {
        "version": 1,
        "request_id": str(request_id),
        "action": "release",
        "reason": "Vendor confirmed the request was not billed",
    }
    path = BASE + str(call_id) + "/reconcile"
    committed_but_response_lost = await admin.api.post(path, json=body)
    assert committed_but_response_lost.status_code == 200
    del committed_but_response_lost  # The client only retained request_id after transport loss.
    receipt_path = f"/api/v1/llm/mutation-receipts/{request_id}?scope=settlement.reconcile"
    receipt = await admin.api.get(receipt_path)
    assert receipt.status_code == 200 and receipt.json()["resource_id"] == str(call_id)
    assert receipt.json()["state"] == "completed"
    assert (await other.api.get(receipt_path)).status_code in (403, 404)
    assert (await member.api.get(receipt_path)).status_code == 403
    replay = await admin.api.post(path, json=body)
    assert replay.status_code == 200
    async with env.sessions() as db:
        actor = await db.get(Membership, admin.member.id)
        actor.role = "member"
        await db.commit()
    assert (await admin.api.get(receipt_path)).status_code == 403


async def test_tagged_and_legacy_usage_reject_missing_cache_or_mixed_units(env):
    admin = await env.client()
    await billing(admin)
    call_id, _, _ = await seed_review(
        env,
        admin,
        admin,
        price={
            "currency": "USD",
            "metric": "tokens",
            "input": "1",
            "output": "2",
            "cache_read": "0",
        },
    )
    path = BASE + str(call_id) + "/reconcile"
    base = {
        "version": 1,
        "request_id": str(uuid4()),
        "action": "settle",
        "reason": "Vendor statement checked",
    }
    invalid = [
        {"metric": "tokens", "input_tokens": 10, "output_tokens": 2},
        {"metric": "tokens", "input_tokens": 10, "output_tokens": 2, "input": 10},
        {"metric": "images", "image_count": 1},
        {"input": 10, "output": 2},  # Legacy is explicit but cannot omit priced cache.
    ]
    for usage in invalid:
        result = await admin.api.post(
            path, json={**base, "request_id": str(uuid4()), "usage": usage}
        )
        assert result.status_code == 422, (usage, result.text)
    no_request_id = await admin.api.post(
        path,
        json={
            "version": 1,
            "action": "settle",
            "usage": {
                "metric": "tokens",
                "input_tokens": 10,
                "output_tokens": 2,
                "cache_read_tokens": 0,
            },
            "reason": "Vendor statement checked",
        },
    )
    assert no_request_id.status_code == 422
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, call_id)
        assert row.status == "review" and row.version == 1


@pytest.mark.parametrize("action", ["settle", "release"])
async def test_old_unknown_hold_survives_window_reset_until_explicit_reconcile(env, action):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    await billing(admin, rules=[{"kind": "fixed_hours", "hours": 1, "points": "100"}])
    call_id, _, _ = await seed_review(
        env,
        admin,
        member,
        price={"currency": "USD", "metric": "characters", "input": "1"},
        age_minutes=48 * 60,
    )
    quota_path = f"/api/v1/llm/members/{member.member.id}/quota"
    before = await admin.api.get(quota_path)
    assert before.status_code == 200
    assert Decimal(before.json()["windows"][0]["reserved"]) == Decimal("18.5")
    payload = {
        "version": 1,
        "request_id": str(uuid4()),
        "action": action,
        "reason": "Historical vendor statement checked after the quota window reset",
    }
    if action == "settle":
        payload["usage"] = tagged("characters", 1000000)
    applied = await admin.api.post(BASE + str(call_id) + "/reconcile", json=payload)
    assert applied.status_code == 200, applied.text
    after = await admin.api.get(quota_path)
    assert after.status_code == 200
    assert Decimal(after.json()["windows"][0]["reserved"]) == 0
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, call_id)
        assert row.status == ("settled" if action == "settle" else "released")
        assert row.ratio == Decimal("37")


async def test_recent_reserved_refuses_preview_and_commit_until_guard_passes(env):
    admin = await env.client()
    await billing(admin)
    call_id, _, _ = await seed_review(
        env,
        admin,
        admin,
        price={"currency": "USD", "metric": "images", "unit": 1, "input": "3"},
        status="reserved",
        age_minutes=0,
    )
    detail = await admin.api.get(BASE + str(call_id) + "/reconciliation")
    assert detail.status_code == 200
    assert detail.json()["eligible"] is False and detail.json()["available_after"]
    body = {
        "version": 1,
        "request_id": str(uuid4()),
        "action": "release",
        "reason": "Confirmed no provider charge",
    }
    preview = await admin.api.post(BASE + str(call_id) + "/reconcile/preview", json=body)
    assert preview.status_code == 409
    result = await admin.api.post(BASE + str(call_id) + "/reconcile", json=body)
    assert result.status_code == 409
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, call_id)
        assert row.status == "reserved" and row.version == 1
