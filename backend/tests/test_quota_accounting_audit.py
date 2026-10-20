"""Accounting regressions with isolated PostgreSQL; no provider calls or real balances."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from uuid import UUID, uuid4

import pytest
from llm_billing_helpers import billing
from test_identity_access import env as identity_env
from test_llm_execution import PRICE, configured
from test_quota_policies import edit, hours, week

from app.modules.llm import settlement
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.models import ModelCall, QuotaClock, UsageSettlement
from app.modules.llm.points import current_conversion
from app.modules.members.service import BusinessActor

env = identity_env
pytestmark = pytest.mark.asyncio
START = datetime(2026, 10, 12, 1, tzinfo=UTC)


async def setup(env, rules=None):
    admin = await env.client()
    policy = await billing(admin, rules=rules or [hours(), week()])
    model, channels = await configured(env, admin, "http://127.0.0.1:9")
    return admin, policy, model, channels


async def entry(env, admin, model, channels, stamp, status="review", amount="1", ratio="100"):
    async with env.sessions() as db:
        conversion = await current_conversion(db, admin.tenant.id)
        log = ModelCall(
            id=uuid4(),
            tenant_id=admin.tenant.id,
            actor_id=admin.user.id,
            model_id=UUID(model["id"]),
            channel_id=UUID(channels[0]["id"]),
            source="desktop",
            kind="chat",
            status="succeeded",
            created_at=stamp,
        )
        db.add(log)
        await db.flush()
        row = UsageSettlement(
            id=log.id,
            tenant_id=admin.tenant.id,
            member_id=admin.member.id,
            currency="USD",
            conversion_id=conversion.id,
            ratio=Decimal(ratio),
            reserved_amount=Decimal(amount),
            amount=Decimal(amount) if status == "settled" else None,
            price=PRICE,
            policy_snapshot={},
            usage={},
            status=status,
            created_at=stamp,
        )
        db.add(row)
        await db.commit()
        return row.id


async def clock(env, admin, stamp):
    async with env.sessions() as db:
        db.add(
            QuotaClock(
                member_id=admin.member.id,
                tenant_id=admin.tenant.id,
                windows={"5": {"start": stamp.isoformat()}},
            )
        )
        await db.commit()


async def quota(env, admin, monkeypatch, stamp, activate=False):
    monkeypatch.setattr(settlement, "now", lambda: stamp)
    async with env.sessions() as db:
        result = await settlement.snapshot(
            db, BusinessActor(admin.user, admin.member, admin.tenant), activate=activate
        )
        await db.commit()
        return result["windows"]


@pytest.mark.parametrize("status", ["reserved", "review", "settled"])
async def test_consumption_belongs_to_admission_window_even_when_unresolved(
    env, monkeypatch, status
):
    admin, _, model, channels = await setup(env)
    row_id = await entry(env, admin, model, channels, START, status=status, amount="0.2")
    await clock(env, admin, START)
    before = await quota(env, admin, monkeypatch, START + timedelta(hours=5, microseconds=-1))
    assert before[0]["remaining"] == "80"
    after = await quota(env, admin, monkeypatch, START + timedelta(hours=5))
    assert after[0]["remaining"] == "100"
    assert after[0]["reserved"] == after[0]["used"] == "0"
    assert after[0]["started_at"] is None  # Reading does not start a new window.
    assert after[1]["remaining"] == "780"  # Still belongs to this week.
    next_week = await quota(env, admin, monkeypatch, datetime(2026, 10, 18, 16, tzinfo=UTC))
    assert next_week[1]["remaining"] == "800"
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, row_id)
        assert row.status == status and row.reserved_amount == Decimal("0.2")


async def test_return_to_expired_duration_includes_intervening_consumption(env, monkeypatch):
    admin, policy, model, channels = await setup(env)
    await clock(env, admin, START - timedelta(days=1))
    changed = await edit(admin, policy, rules=[hours(duration=24), week()])
    assert changed.status_code == 200
    await entry(env, admin, model, channels, START, status="settled", amount="0.2")
    await entry(env, admin, model, channels, START + timedelta(minutes=1), amount="0.1")
    restored = await edit(admin, changed.json(), rules=[hours(), week()])
    assert restored.status_code == 200
    windows = await quota(env, admin, monkeypatch, START + timedelta(hours=1))
    assert windows[0]["used"] == "20" and windows[0]["reserved"] == "10"
    assert windows[0]["remaining"] == "70"
    assert datetime.fromisoformat(windows[0]["started_at"]) == START


async def test_late_settlement_changes_original_week_only_and_uses_historical_ratio(
    env, monkeypatch
):
    admin, _, model, channels = await setup(env)
    row_id = await entry(env, admin, model, channels, START, amount="0.2")
    await clock(env, admin, START)
    await quota(env, admin, monkeypatch, START + timedelta(hours=6), activate=True)
    async with env.sessions() as db:
        assert await settlement.complete(
            db,
            row_id,
            {"input_tokens": 100, "output_tokens": 10, "cache_read_tokens": 20},
            delivered=True,
            manual=True,
        )
        assert not await settlement.complete(db, row_id, {}, delivered=True, manual=True)
        await db.commit()
    windows = await quota(env, admin, monkeypatch, START + timedelta(hours=6))
    assert windows[0]["remaining"] == "100"
    assert windows[1]["reserved"] == "0" and windows[1]["used"] == "0.0284"


@pytest.mark.parametrize("status", ["review", "settled"])
async def test_balance_preserves_more_than_default_decimal_precision(env, monkeypatch, status):
    cap = "999999999999999999.123456789012"
    admin, _, model, channels = await setup(env, [hours(cap)])
    amount, ratio = "123456.123456789012345678", "999999.123456789012"
    await entry(env, admin, model, channels, START, status, amount, ratio)
    await clock(env, admin, START)
    windows = await quota(env, admin, monkeypatch, START + timedelta(seconds=1))
    with localcontext() as context:
        context.prec = 80
        assert Decimal(windows[0]["remaining"]) == Decimal(cap) - Decimal(amount) * Decimal(ratio)


async def test_reservation_timestamp_is_the_same_instant_as_window_admission(env, monkeypatch):
    admin, _, model, channels = await setup(env)
    monkeypatch.setattr(settlement, "now", lambda: START)
    async with env.sessions() as db:
        log = ModelCall(
            id=uuid4(),
            tenant_id=admin.tenant.id,
            actor_id=admin.user.id,
            model_id=UUID(model["id"]),
            channel_id=UUID(channels[0]["id"]),
            source="desktop",
            kind="chat",
            status="pending",
        )
        db.add(log)
        await settlement.reserve(
            db,
            BusinessActor(admin.user, admin.member, admin.tenant),
            log,
            CatalogInput.model_validate(
                {k: v for k, v in model.items() if k in CatalogInput.model_fields}
            ),
            ChatInput(model=model["slug"], messages=[{"role": "user", "content": "x"}]),
            None,
        )
        await db.commit()
        row = await db.get(UsageSettlement, log.id)
        assert row.created_at == START
        windows = await settlement.snapshot(
            db, BusinessActor(admin.user, admin.member, admin.tenant)
        )
        assert windows["windows"][0]["reserved"] == "0.28"


async def test_member_ranking_uses_exact_points_when_lower_digits_differ(env):
    admin, _, model, channels = await setup(env)
    member = await env.client(role="member", tenant=admin.tenant)
    smaller, larger = sorted([admin, member], key=lambda person: str(person.member.id))
    await entry(
        env, smaller, model, channels, START, "settled", "999999999998999.123456789012345678", "1"
    )
    await entry(
        env, larger, model, channels, START, "settled", "999999999998999.123456789012345679", "1"
    )
    response = await admin.api.get(
        "/api/v1/llm/dashboard",
        params={
            "from": START.isoformat(),
            "to": (START + timedelta(days=1)).isoformat(),
            "rank": "points",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["members"][0]["key"] == str(larger.member.id)
