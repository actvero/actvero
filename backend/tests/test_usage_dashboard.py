"""Dashboard conservation, civil time and isolation on disposable PostgreSQL."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from test_call_queries_integration import evidence, seed_calls
from test_channel_health import channel
from test_identity_access import env as identity_env

from app.modules.auth.models import WebSession
from app.modules.llm.call_queries import CallFilters
from app.modules.llm.dashboard import boundaries
from app.modules.llm.models import ModelCall
from app.modules.mcp.credentials import SHARED
from app.modules.mcp.models import McpActivity, McpHealth, McpService
from app.modules.tenants.models import Tenant

env = identity_env
START = datetime(2026, 10, 1, tzinfo=UTC)
BASE = {"from": START.isoformat(), "to": (START + timedelta(days=1)).isoformat()}
API = "/api/v1/llm/dashboard"


@pytest.mark.parametrize(
    "zone,start,end,kind,length",
    [
        ("America/New_York", "2026-03-08T00:00:00-05:00", "2026-03-09T00:00:00-04:00", "hour", 23),
        ("America/New_York", "2026-11-01T00:00:00-04:00", "2026-11-02T00:00:00-05:00", "hour", 25),
        ("America/New_York", "2026-03-07T00:00:00-05:00", "2026-03-10T00:00:00-04:00", "day", 3),
        ("Asia/Shanghai", "2026-10-01T08:30:00+08:00", "2026-10-01T10:15:00+08:00", "hour", 3),
        ("Asia/Kathmandu", "2026-10-01T00:00:00+05:45", "2026-10-02T00:00:00+05:45", "hour", 24),
    ],
)
def test_boundaries_are_half_open_monotonic_and_dst_aware(zone, start, end, kind, length):
    filters = CallFilters(uuid4(), datetime.fromisoformat(start), datetime.fromisoformat(end), zone)
    actual, edges = boundaries(filters, kind)
    assert actual == kind and len(edges) == length + 1
    assert edges[0] == filters.from_time and edges[-1] == filters.to_time
    assert all(left < right for left, right in zip(edges, edges[1:], strict=False))
    assert (
        sum((right - left).total_seconds() for left, right in zip(edges, edges[1:], strict=False))
        == (filters.to_time.astimezone(UTC) - filters.from_time.astimezone(UTC)).total_seconds()
    )


@pytest.mark.parametrize(
    "changes,kind",
    [
        ({"timezone_name": "not/a-zone"}, "day"),
        ({"to_time": START + timedelta(days=91)}, "auto"),
        ({"to_time": START}, "day"),
        ({"to_time": START + timedelta(days=40)}, "hour"),
        ({"source": "all"}, "auto"),
        ({"channel_id": uuid4(), "unknown_channel": True}, "day"),
    ],
)
def test_invalid_ranges_and_excessive_buckets_are_rejected(changes, kind):
    with pytest.raises(HTTPException) as error:
        boundaries(replace(CallFilters(uuid4(), START, START + timedelta(days=1)), **changes), kind)
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_aggregate_matches_summary_buckets_rankings_and_current_hold(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    specs = [
        {
            "label": "zero",
            "at": START,
            "settlement": "settled",
            "amount": "0.12",
            "ratio": "37",
            "attempts": [
                {
                    "status": "succeeded",
                    "sent": True,
                    "usage_evidence": [evidence("input_tokens", 0)],
                }
            ],
        },
        {
            "label": "known",
            "at": START + timedelta(hours=1),
            "source": "access_key",
            "settlement": "settled",
            "amount": "1.1",
            "currency": "CNY",
            "ratio": "2",
            "attempts": [
                {
                    "status": "succeeded",
                    "sent": True,
                    "usage_evidence": [evidence("input_tokens", 11)],
                }
            ],
        },
        {
            "label": "unknown",
            "at": START + timedelta(hours=2),
            "result": "unknown",
            "settlement": "review",
        },
        {
            "label": "future",
            "at": START + timedelta(days=2),
            "settlement": "review",
            "reserved": "0.2",
            "ratio": "2",
        },
        {"label": "exclusive_end", "at": START + timedelta(days=1)},
        {"label": "diagnostic", "at": START, "source": "channel_diagnostic"},
    ]
    ids, _, _ = await seed_calls(env, admin, member, specs)
    async with env.sessions() as db:
        for key, duration in (("zero", 0), ("known", 2500), ("unknown", 900)):
            (await db.get(ModelCall, ids[key])).duration_ms = duration
        await db.commit()
    response = await admin.api.get(API, params=BASE)
    assert response.status_code == 200, response.text
    data = response.json()
    old = (await admin.api.get("/api/v1/llm/usage-summary", params=BASE)).json()
    assert data["summary"]["calls"] == old["calls"] == 3
    assert data["summary"]["settled_points"] == old["settled_points"] == "6.64"
    assert sum(row["calls"] for row in data["timeline"]) == 3
    assert len(data["timeline"]) == 24
    tokens = next(row for row in data["summary"]["metrics"] if row["field"] == "input_tokens")
    assert tokens == {
        "field": "input_tokens",
        "metric": "tokens",
        "sum": "11",
        "known_calls": 2,
        "unknown_calls": 1,
    }
    assert data["timeline"][0]["metrics"][0]["known_calls"] == 1
    assert data["timeline"][2]["metrics"][0]["unknown_calls"] == 1
    assert data["members"][0]["key"] == str(member.member.id)
    assert data["members"][0]["calls"] == 3
    assert data["summary"]["current_held"]["points"] == "18.9"
    assert data["performance"]["samples"] == 2
    assert data["performance"]["average_ms"] == 1250
    assert data["performance"]["p95_ms"] == 2500
    assert sum(row["calls"] for row in data["flow"]) == 3
    diagnostic = await admin.api.get(API, params={**BASE, "source": "diagnostic"})
    assert diagnostic.json()["summary"]["settled_points"] is None
    assert diagnostic.json()["timeline"][0]["settled_points"] is None
    assert not diagnostic.json()["summary"]["current_held"]["applicable"]


@pytest.mark.asyncio
async def test_flow_uses_final_proof_and_drill_matches_without_settlement(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    ids, model, initial = await seed_calls(
        env,
        admin,
        member,
        [
            {"label": label, "at": START}
            for label in ["fallback", "unknown", "malformed", "foreign"]
        ],
    )
    async with env.sessions() as db:
        final = channel(admin.tenant.id)
        final.name = "final"
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        foreign_tenant = Tenant(name="other org", instance_slot=None)
        db.add_all([final, foreign_tenant])
        await db.flush()
        foreign = channel(foreign_tenant.id)
        db.add(foreign)
        await db.flush()
        for label, attempts in {
            "fallback": [
                {"channel_id": str(initial), "status": "failed"},
                {
                    "evidence_version": 1,
                    "channel_id": str(final.id),
                    "sent": True,
                    "upstream_terminal": True,
                    "status": "succeeded",
                },
            ],
            "unknown": [
                {
                    "evidence_version": 1,
                    "channel_id": str(initial),
                    "sent": True,
                    "upstream_terminal": False,
                    "status": "unknown",
                }
            ],
            "malformed": [
                {
                    "evidence_version": "1",
                    "channel_id": str(initial),
                    "sent": "true",
                    "upstream_terminal": "true",
                    "status": "succeeded",
                }
            ],
            "foreign": [
                {
                    "evidence_version": 1,
                    "channel_id": str(foreign.id),
                    "sent": True,
                    "upstream_terminal": True,
                    "status": "succeeded",
                }
            ],
        }.items():
            (await db.get(ModelCall, ids[label])).attempts = attempts
        await db.commit()
        final_id = str(final.id)
    data = (await admin.api.get(API, params=BASE)).json()
    assert data["summary"]["calls"] == 4 and sum(row["calls"] for row in data["flow"]) == 4
    assert {str(row["channel_id"]) for row in data["flow"]} == {final_id, "None"}
    unknown = next(row for row in data["flow"] if row["channel_id"] is None)
    assert unknown["calls"] == 3
    for extra, expected in [
        ({"channel_id": final_id}, {"fallback"}),
        ({"unknown_channel": True}, {"unknown", "malformed", "foreign"}),
    ]:
        params = {**BASE, "member_id": str(member.member.id), "model_id": str(model), **extra}
        listing = await admin.api.get("/api/v1/llm/calls", params=params)
        assert listing.status_code == 200, listing.text
        assert {row["id"] for row in listing.json()["items"]} == {str(ids[key]) for key in expected}
        chart = await admin.api.get(API, params=params)
        assert chart.status_code == 200, chart.text
        assert chart.json()["summary"]["calls"] == len(expected)
    assert (
        await admin.api.get(API, params={**BASE, "channel_id": final_id, "unknown_channel": True})
    ).status_code == 422


@pytest.mark.asyncio
async def test_ownership_selected_members_and_read_only_limit(env, monkeypatch):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    ids, _, _ = await seed_calls(
        env, admin, member, [{"label": "one", "at": START}, {"label": "two", "at": START}]
    )
    assert (await member.api.get(API, params=BASE)).status_code == 403
    assert (await member.api.get("/api/v1/overview")).status_code == 403
    foreign = uuid4()
    response = await admin.api.get(
        API, params={**BASE, "selected_members": f"{member.member.id},{foreign}"}
    )
    assert response.status_code == 200, response.text
    assert set(response.json()["member_timelines"]) == {str(member.member.id)}
    assert (
        sum(row["calls"] for row in response.json()["member_timelines"][str(member.member.id)]) == 2
    )
    assert (
        await admin.api.get(
            API, params={**BASE, "selected_members": ",".join(str(uuid4()) for _ in range(6))}
        )
    ).status_code == 422
    import app.modules.llm.dashboard as module

    monkeypatch.setattr(module, "MAX_CALLS", 1)
    limited = await admin.api.get(API, params=BASE)
    assert limited.status_code == 422 and "截断" in limited.text
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(ModelCall.id))) == len(ids)


@pytest.mark.asyncio
async def test_personal_overview_and_tenant_scope(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    now = datetime.now(UTC) - timedelta(minutes=1)
    ids, _, _ = await seed_calls(
        env,
        admin,
        member,
        [
            {"label": "own", "at": now, "settlement": "settled", "amount": "0.2", "ratio": "4"},
            {"label": "other", "at": now, "actor_id": admin.user.id},
            {"label": "review", "at": now - timedelta(days=2), "settlement": "review"},
            {"label": "diagnostic", "at": now, "source": "channel_diagnostic"},
        ],
    )
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        other = Tenant(name="hidden organization", instance_slot=None)
        db.add(other)
        await db.flush()
        foreign_channel = channel(other.id)
        db.add(foreign_channel)
        await db.flush()
        db.add(
            ModelCall(
                tenant_id=other.id,
                channel_id=foreign_channel.id,
                model_id=None,
                actor_id=member.user.id,
                source="channel_diagnostic",
                kind="chat",
                status="succeeded",
                created_at=now,
            )
        )
        await db.commit()
    view = await member.api.get("/api/v1/account/overview")
    assert view.status_code == 200, view.text
    assert view.json()["calls"] == 1 and view.json()["settled_points"] == "0.8"
    assert view.json()["review_calls"] == 1
    data = await admin.api.get(
        API,
        params={
            "from": (now - timedelta(hours=1)).isoformat(),
            "to": (now + timedelta(hours=1)).isoformat(),
            "source": "diagnostic",
        },
    )
    assert data.status_code == 200 and data.json()["summary"]["calls"] == 1
    async with env.sessions() as db:
        session = await db.get(WebSession, member.session.id)
        session.expires_at = now - timedelta(hours=1)
        await db.commit()
    assert (await member.api.get("/api/v1/account/overview")).status_code == 401


@pytest.mark.asyncio
async def test_overview_health_owner_and_business_activity_are_distinct(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    now = datetime.now(UTC)
    async with env.sessions() as db:
        personal = McpService(
            tenant_id=admin.tenant.id,
            name="personal",
            transport="http",
            enabled=True,
            auth_mode="personal",
            connection_options={"health_enabled": True},
        )
        shared = McpService(
            tenant_id=admin.tenant.id,
            name="shared",
            transport="http",
            enabled=True,
            connection_options={"health_enabled": True},
        )
        stale = McpService(
            tenant_id=admin.tenant.id,
            name="stale",
            transport="http",
            enabled=True,
            connection_options={"health_enabled": True},
        )
        db.add_all([personal, shared, stale])
        await db.flush()
        db.add_all(
            [
                McpHealth(
                    service_id=personal.id,
                    owner_id=member.member.id,
                    checked_at=now,
                    next_check_at=now + timedelta(hours=1),
                ),
                McpHealth(
                    service_id=shared.id,
                    owner_id=SHARED,
                    checked_at=now,
                    next_check_at=now + timedelta(hours=1),
                    error="test",
                ),
                McpHealth(
                    service_id=stale.id,
                    owner_id=SHARED,
                    checked_at=now - timedelta(hours=1),
                    next_check_at=now - timedelta(hours=1),
                ),
            ]
        )
        for category in ("call", "connection"):
            db.add(
                McpActivity(
                    tenant_id=admin.tenant.id,
                    service_id=shared.id,
                    service_name="shared",
                    actor_name="测试成员",
                    owner_id=SHARED,
                    category=category,
                    operation="tools/call",
                    result="success",
                    duration_ms=10,
                    request_id=str(uuid4()),
                )
            )
        await db.commit()
    async with env.sessions() as db:
        before = await db.scalar(select(func.count(McpActivity.id)))
    response = await admin.api.get("/api/v1/overview")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mcp"] == {"total": 3, "enabled": 3}
    assert result["mcp_checked"] == 0 and result["mcp_failed"] == 1 and result["mcp_unchecked"] == 2
    assert result["mcp_calls"] == 1
    async with env.sessions() as db:
        assert await db.scalar(select(func.count(McpActivity.id))) == before


@pytest.mark.asyncio
async def test_top_n_omission_conserves_totals_and_equal_names_keep_distinct_ids(env):
    admin = await env.client()
    members = [await env.client(role="member", tenant=admin.tenant) for _ in range(7)]
    specs = [
        {"label": str(index), "at": START, "actor_id": member.user.id}
        for index, member in enumerate(members)
    ]
    await seed_calls(env, admin, members[0], specs)
    data = (
        await admin.api.get(
            API, params={**BASE, "top": 5, "selected_members": str(members[0].member.id)}
        )
    ).json()
    assert data["member_count"] == 7 and len(data["members"]) == 5
    assert len({row["key"] for row in data["members"]}) == 5
    assert (
        sum(row["calls"] for row in data["members"]) + data["other_members"]["calls"]
        == data["summary"]["calls"]
        == 7
    )
    assert sum(row["calls"] for row in data["flow"]) + data["other_flow_calls"] == 7
    assert data["member_names"] == {str(members[0].member.id): "测试成员"}


@pytest.mark.asyncio
async def test_saas_session_switches_tenant_without_union_or_operator_bypass(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    await seed_calls(env, admin, member, [{"label": "org1", "at": START}])
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        other = Tenant(name="second organization")
        db.add(other)
        await db.flush()
        from app.modules.members.models import Membership

        db.add(
            Membership(
                tenant_id=other.id, user_id=admin.user.id, role="member", source="invitation"
            )
        )
        session = await db.get(WebSession, admin.session.id)
        session.tenant_id = admin.tenant.id
        await db.commit()
        other_id = other.id
    first = await admin.api.get(API, params=BASE)
    assert first.status_code == 200 and first.json()["summary"]["calls"] == 1
    async with env.sessions() as db:
        session = await db.get(WebSession, admin.session.id)
        session.tenant_id = other_id
        await db.commit()
    assert (await admin.api.get(API, params=BASE)).status_code == 403
    own = await admin.api.get("/api/v1/account/overview")
    assert own.status_code == 200 and own.json()["calls"] == 0
