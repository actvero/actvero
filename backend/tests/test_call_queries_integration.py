"""G6-03 call-root queries against isolated PostgreSQL and the real management API."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from llm_billing_helpers import billing
from sqlalchemy import select
from test_channel_health import catalog, channel
from test_identity_access import env as identity_env

from app.modules.llm.catalog_schemas import TokenPrice
from app.modules.llm.models import ModelCall, PointConversion, UsageSettlement
from app.modules.members.models import Membership

env = identity_env
pytestmark = pytest.mark.asyncio
CALLS = "/api/v1/llm/calls"
SUMMARY = "/api/v1/llm/usage-summary"


async def seed_calls(env, admin, member, cases):
    """Insert old and current logical calls, with optional historical settlement snapshots."""
    await billing(admin)
    async with env.sessions() as db:
        conversion = await db.scalar(
            select(PointConversion).where(PointConversion.tenant_id == admin.tenant.id)
        )
        assert conversion is not None
        conversions = {conversion.currency: conversion}
        upstream = channel(admin.tenant.id)
        model, _ = catalog(admin.tenant.id, [upstream], mode="fixed")
        db.add_all([upstream, model])
        await db.flush()
        ids = {}
        for spec in cases:
            attempts = deepcopy(spec.get("attempts", []))
            if not spec.get("legacy_attempts"):
                for attempt in attempts:
                    if not isinstance(attempt, dict):
                        continue
                    attempt.setdefault("attempt_id", str(uuid4()))
                    attempt.setdefault("evidence_version", 1)
                    if any(
                        isinstance(item, dict)
                        and item.get("source") == "upstream"
                        and item.get("phase") == "terminal"
                        and item.get("complete") is True
                        for item in attempt.get("usage_evidence", [])
                    ):
                        attempt.setdefault("upstream_terminal", True)
                    for item in attempt.get("usage_evidence", []):
                        if isinstance(item, dict) and item.get("attempt_id") is None:
                            item["attempt_id"] = attempt["attempt_id"]
            call = ModelCall(
                id=uuid4(),
                tenant_id=admin.tenant.id,
                model_id=None if spec.get("source") == "channel_diagnostic" else model.id,
                channel_id=upstream.id,
                actor_id=spec.get("actor_id", member.user.id),
                source=spec.get("source", "desktop"),
                kind=spec.get("kind", "chat"),
                status=spec.get("result", "succeeded"),
                termination_code=spec.get("termination_code"),
                attempts=attempts,
                usage=spec.get("usage", {}),
                created_at=spec["at"],
            )
            db.add(call)
            await db.flush()
            ids[spec["label"]] = call.id
            if spec.get("settlement") is None:
                continue
            currency = spec.get("currency", "USD")
            if currency not in conversions:
                extra = PointConversion(
                    tenant_id=admin.tenant.id,
                    currency=currency,
                    points_per_currency=Decimal(spec.get("ratio", "37")),
                    version=len(conversions) + 1,
                )
                db.add(extra)
                await db.flush()
                conversions[currency] = extra
            row = UsageSettlement(
                id=call.id,
                tenant_id=admin.tenant.id,
                member_id=member.member.id,
                conversion_id=conversions[currency].id,
                currency=currency,
                ratio=Decimal(spec.get("ratio", "37")),
                reserved_amount=Decimal(spec.get("reserved", "0.5")),
                amount=Decimal(spec["amount"]) if spec.get("amount") is not None else None,
                price=TokenPrice.model_validate(
                    spec.get("price", {"currency": "USD", "metric": "tokens", "input": "1"})
                ).model_dump(mode="json"),
                policy_snapshot={"status": "active", "policy": {"id": "historical"}},
                usage=spec.get("settlement_usage", {}),
                status=spec["settlement"],
                version=1,
                created_at=spec["at"],
            )
            db.add(row)
        await db.commit()
        return ids, model.id, upstream.id


def evidence(field, value, *, source="upstream", phase="terminal", complete=True):
    return {
        "field": field,
        "value": value,
        "metric": {
            "input_tokens": "tokens",
            "output_tokens": "tokens",
            "cache_read_tokens": "tokens",
            "input_characters": "characters",
            "search_units": "searches",
            "image_count": "images",
        }[field],
        "source": source,
        "complete": complete,
        "phase": phase,
        "attempt_id": None,
        "evidence_version": 1,
    }


async def test_call_root_keeps_result_settlement_and_diagnostic_axes_separate(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    when = datetime(2026, 10, 1, 12, tzinfo=UTC)
    ids, _, _ = await seed_calls(
        env,
        admin,
        member,
        [
            {
                "label": "success_review",
                "at": when,
                "source": "desktop",
                "result": "succeeded",
                "settlement": "review",
                "attempts": [
                    {"number": 1, "status": "unknown"},
                    {"number": 2, "status": "success"},
                ],
            },
            {
                "label": "failure_settled",
                "at": when + timedelta(seconds=1),
                "source": "access_key",
                "result": "failed",
                "settlement": "settled",
                "amount": "1",
            },
            {
                "label": "channel_diagnostic",
                "at": when + timedelta(seconds=2),
                "source": "channel_diagnostic",
                "result": "succeeded",
                "attempts": [{"number": 1, "status": "success"}],
            },
            {
                "label": "route_diagnostic",
                "at": when + timedelta(seconds=3),
                "source": "admin_route_test",
                "result": "failed",
            },
        ],
    )
    ordinary = await admin.api.get(CALLS)
    assert ordinary.status_code == 200, ordinary.text
    assert ordinary.json()["total"] == 2
    assert {item["id"] for item in ordinary.json()["items"]} == {
        str(ids["success_review"]),
        str(ids["failure_settled"]),
    }
    filtered = await admin.api.get(
        CALLS, params={"result_status": "success", "settlement_status": "review"}
    )
    assert filtered.status_code == 200, filtered.text
    assert [item["id"] for item in filtered.json()["items"]] == [str(ids["success_review"])]
    assert filtered.json()["items"][0]["attempt_count"] == 2
    assert filtered.json()["items"][0]["settlement_status"] == "review"
    diagnostics = await admin.api.get(CALLS, params={"source": "diagnostic"})
    assert diagnostics.status_code == 200, diagnostics.text
    assert {item["id"] for item in diagnostics.json()["items"]} == {
        str(ids["channel_diagnostic"]),
        str(ids["route_diagnostic"]),
    }
    assert all(
        item["settlement_status"] == "not_applicable" for item in diagnostics.json()["items"]
    )
    assert all(item["reserved_points"] is None for item in diagnostics.json()["items"])
    assert all(item["points"] is None for item in diagnostics.json()["items"])
    actor_filtered = await admin.api.get(
        CALLS, params={"source": "diagnostic", "member_id": str(member.member.id)}
    )
    assert actor_filtered.status_code == 200, actor_filtered.text
    assert actor_filtered.json()["total"] == 2
    assert all(item["member_name"] == member.user.name for item in actor_filtered.json()["items"])
    by_id = await admin.api.get(CALLS, params={"call_id": str(ids["channel_diagnostic"])})
    assert by_id.status_code == 200 and by_id.json()["total"] == 0
    diagnostic_detail = await admin.api.get(CALLS + "/" + str(ids["channel_diagnostic"]))
    assert diagnostic_detail.status_code == 200, diagnostic_detail.text
    assert diagnostic_detail.json()["settlement"] is None
    assert diagnostic_detail.json()["call"]["model_id"] is None


async def test_call_detail_projects_only_safe_attempt_evidence_and_old_sparse_rows(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    secret = "DO_NOT_LEAK_PROMPT_OR_KEY"
    ids, _, _ = await seed_calls(
        env,
        admin,
        member,
        [
            {
                "label": "old",
                "at": datetime(2026, 10, 1, tzinfo=UTC),
                "settlement": "review",
                "legacy_attempts": True,
                "attempts": [
                    {"number": 1, "status": "unknown"},
                    {
                        "number": 2,
                        "attempt_id": str(uuid4()),
                        "sent": True,
                        "status": "success",
                        "usage": {"input_tokens": 13},
                        "usage_evidence": [
                            {
                                "field": "input_tokens",
                                "value": 13,
                                "metric": "tokens",
                                "source": "upstream",
                                "complete": False,
                                "phase": "partial",
                                "attempt_id": None,
                                "evidence_version": 1,
                                "provider_secret": secret,
                            }
                        ],
                        "prompt": secret,
                        "secret_key": secret,
                        "upstream_error_body": secret,
                    },
                ],
                "usage": {"input_tokens": 13},
            }
        ],
    )
    result = await admin.api.get(CALLS + "/" + str(ids["old"]))
    assert result.status_code == 200, result.text
    data = result.json()
    assert secret not in result.text
    assert len(data["attempts"]) == 2
    assert data["attempts"][0]["sent"] is None
    assert data["attempts"][0]["usage_evidence"] == []
    assert data["attempts"][1]["usage_evidence"][0]["value"] == 13
    assert data["attempts"][1]["usage_evidence"][0]["complete"] is False
    assert data["settlement"]["status"] == "review"


async def test_aware_time_range_is_half_open_and_rejects_invalid_bounds(env):
    admin = await env.client()
    start = datetime(2026, 10, 1, tzinfo=UTC)
    ids, _, _ = await seed_calls(
        env,
        admin,
        admin,
        [
            {"label": "left", "at": start, "settlement": "review"},
            {"label": "inside", "at": start + timedelta(hours=23), "settlement": "review"},
            {"label": "right", "at": start + timedelta(days=1), "settlement": "review"},
        ],
    )
    period = {
        "from": "2026-10-01T08:00:00+08:00",
        "to": "2026-10-02T08:00:00+08:00",
        "timezone": "Asia/Shanghai",
    }
    result = await admin.api.get(CALLS, params=period)
    assert result.status_code == 200, result.text
    assert {item["id"] for item in result.json()["items"]} == {
        str(ids["left"]),
        str(ids["inside"]),
    }
    invalid = [
        {"from": period["from"]},
        {"to": period["to"]},
        {**period, "from": "2026-10-01T08:00:00"},
        {**period, "to": period["from"]},
        {**period, "to": "2027-01-01T08:00:01+08:00"},
        {**period, "timezone": "Mars/Olympus"},
    ]
    for params in invalid:
        response = await admin.api.get(CALLS, params=params)
        assert response.status_code == 422, (params, response.text)
        summary_error = await admin.api.get(SUMMARY, params=params)
        assert summary_error.status_code == 422, (params, summary_error.text)
    page_zero = await admin.api.get(CALLS, params={"page": 0})
    assert page_zero.status_code == 422
    exact_ninety = await admin.api.get(
        CALLS,
        params={"from": start.isoformat(), "to": (start + timedelta(days=90)).isoformat()},
    )
    assert exact_ninety.status_code == 200
    assert (await admin.api.get(SUMMARY)).status_code == 422


async def test_summary_uses_historical_points_currency_and_separate_metric_buckets(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    ids, _, _ = await seed_calls(
        env,
        admin,
        member,
        [
            {
                "label": "tokens",
                "at": at,
                "settlement": "settled",
                "amount": "2",
                "ratio": "37",
                "price": {"currency": "USD", "metric": "tokens", "input": "1", "output": "1"},
                "settlement_usage": {"input_tokens": 100, "output_tokens": 20},
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "status": "unknown",
                        "usage_evidence": [
                            evidence("input_tokens", 50),
                            evidence("output_tokens", 5),
                        ],
                    },
                    {
                        "number": 2,
                        "sent": True,
                        "status": "success",
                        "usage_evidence": [
                            evidence("input_tokens", 50),
                            evidence("output_tokens", 15),
                        ],
                    },
                ],
            },
            {
                "label": "characters",
                "at": at + timedelta(seconds=1),
                "kind": "embedding",
                "settlement": "settled",
                "amount": "3",
                "currency": "EUR",
                "ratio": "5",
                "price": {"currency": "EUR", "metric": "characters", "input": "1"},
                "settlement_usage": {"input_characters": 50},
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "usage_evidence": [
                            evidence(
                                "input_characters",
                                50,
                                source="validated_input",
                                phase="validated_input",
                            )
                        ],
                    }
                ],
            },
            {
                "label": "images",
                "at": at + timedelta(seconds=2),
                "kind": "image_generation",
                "settlement": "settled",
                "amount": "4",
                "price": {"currency": "USD", "metric": "images", "unit": 1, "input": "2"},
                "settlement_usage": {"image_count": 2},
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "usage_evidence": [
                            evidence(
                                "image_count",
                                2,
                                source="confirmed_delivery",
                                phase="confirmed_delivery",
                            )
                        ],
                    }
                ],
            },
            {
                "label": "search",
                "at": at + timedelta(seconds=3),
                "kind": "rerank",
                "settlement": "settled",
                "amount": "5",
                "price": {"currency": "USD", "metric": "search_units", "input": "1"},
                "settlement_usage": {"search_units": 7},
                "attempts": [
                    {"number": 1, "sent": True, "usage_evidence": [evidence("search_units", 7)]}
                ],
            },
            {
                "label": "recent_review",
                "at": at + timedelta(seconds=4),
                "result": "succeeded",
                "settlement": "review",
                "reserved": "0.5",
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "status": "unknown",
                        "usage": {"input_tokens": 999},
                        "usage_evidence": [evidence("input_tokens", 999, complete=False)],
                    }
                ],
            },
            {
                "label": "old_review",
                "at": at - timedelta(days=120),
                "result": "unknown",
                "settlement": "review",
                "reserved": "0.75",
            },
            {
                "label": "diagnostic",
                "at": at + timedelta(seconds=5),
                "source": "channel_diagnostic",
                "result": "succeeded",
                "usage": {"input_tokens": 123456},
            },
        ],
    )
    period = {
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-02T00:00:00+00:00",
        "timezone": "UTC",
    }
    response = await admin.api.get(SUMMARY, params=period)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["calls"] == 5
    assert data["attempts"] == 6
    assert Decimal(data["settled_points"]) == Decimal("422")
    amounts = {item["currency"]: Decimal(item["amount"]) for item in data["amounts_by_currency"]}
    assert amounts == {"USD": Decimal("11"), "EUR": Decimal("3")}
    metrics = {(item["metric"], item["field"]): item for item in data["metrics"]}
    for metric, field, expected in (
        ("tokens", "input_tokens", 100),
        ("tokens", "output_tokens", 20),
        ("characters", "input_characters", 50),
        ("images", "image_count", 2),
        ("search_units", "search_units", 7),
    ):
        assert Decimal(metrics[metric, field]["sum"]) == expected
    assert Decimal(data["current_held"]["points"]) == Decimal("46.25")
    assert data["current_held"]["applicable"] is True
    operation_groups = {item["key"]: item for item in data["by_operation"]}
    assert operation_groups["chat"]["calls"] == 2
    assert Decimal(operation_groups["embedding"]["settled_points"]) == Decimal("15")
    assert Decimal(operation_groups["image_generation"]["settled_points"]) == Decimal("148")
    assert len(data["by_model"]) == 1 and data["by_model"][0]["calls"] == 5
    detail = await admin.api.get(CALLS + "/" + str(ids["tokens"]))
    assert detail.status_code == 200
    assert Decimal(detail.json()["settlement"]["points"]) == Decimal("74")
    # The last attempt has 50 tokens; the accepted settlement holds 100 for the call.
    assert Decimal(metrics["tokens", "input_tokens"]["sum"]) == 100
    assert metrics["tokens", "input_tokens"]["known_calls"] == 1
    assert metrics["tokens", "input_tokens"]["unknown_calls"] == 1


async def test_current_held_matches_unfiltered_held_rows_across_old_windows(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    at = datetime(2026, 10, 1, tzinfo=UTC)
    ids, model_id, _ = await seed_calls(
        env,
        admin,
        member,
        [
            {
                "label": "old",
                "at": at - timedelta(days=120),
                "settlement": "review",
                "reserved": "0.5",
            },
            {"label": "new", "at": at, "settlement": "reserved", "reserved": "0.25"},
            {"label": "done", "at": at, "settlement": "settled", "amount": "1"},
        ],
    )
    held = await admin.api.get(
        CALLS,
        params={
            "held": "true",
            "member_id": str(member.member.id),
            "model_id": str(model_id),
            "operation": "chat",
        },
    )
    assert held.status_code == 200, held.text
    assert {item["id"] for item in held.json()["items"]} == {str(ids["old"]), str(ids["new"])}
    listed = sum(Decimal(item["reserved_points"]) for item in held.json()["items"])
    period = {
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-02T00:00:00+00:00",
        "timezone": "UTC",
        "member_id": str(member.member.id),
        "model_id": str(model_id),
        "operation": "chat",
        "result_status": "failed",
        "settlement_status": "settled",
    }
    summary = await admin.api.get(SUMMARY, params=period)
    assert summary.status_code == 200, summary.text
    assert summary.json()["calls"] == 0
    assert Decimal(summary.json()["current_held"]["points"]) == listed == Decimal("27.75")
    assert summary.json()["current_held"]["scope"] == {
        "member_id": str(member.member.id),
        "model_id": str(model_id),
        "operation": "chat",
        "source": "member",
    }
    for forbidden in (
        {"from": period["from"], "to": period["to"]},
        {"result_status": "failed"},
        {"settlement_status": "review"},
        {"call_id": str(ids["old"])},
        {"source": "diagnostic"},
        {"source": "all"},
    ):
        invalid = await admin.api.get(CALLS, params={"held": "true", **forbidden})
        assert invalid.status_code == 422, (forbidden, invalid.text)
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, ids["old"])
        row.status = "released"
        row.version += 1
        await db.commit()
    after = await admin.api.get(SUMMARY, params=period)
    assert after.status_code == 200
    assert Decimal(after.json()["current_held"]["points"]) == Decimal("9.25")


async def test_partial_wrong_source_and_conflicting_evidence_remain_unknown(env):
    admin = await env.client()
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    await seed_calls(
        env,
        admin,
        admin,
        [
            {
                "label": "partial",
                "at": at,
                "settlement": "review",
                "usage": {"input_tokens": 999},
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "usage_evidence": [evidence("input_tokens", 999, complete=False)],
                    }
                ],
            },
            {
                "label": "wrong_source",
                "at": at + timedelta(seconds=1),
                "settlement": "settled",
                "amount": "1",
                "settlement_usage": {"input_tokens": 100},
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "usage_evidence": [evidence("input_tokens", 100, source="unknown")],
                    }
                ],
            },
            {
                "label": "conflict",
                "at": at + timedelta(seconds=2),
                "settlement": "settled",
                "amount": "1",
                "settlement_usage": {"input_tokens": 200},
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "usage_evidence": [
                            evidence("input_tokens", 100),
                            evidence("input_tokens", 200),
                        ],
                    }
                ],
            },
            {
                "label": "false_terminal",
                "at": at + timedelta(seconds=3),
                "settlement": "settled",
                "amount": "1",
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "usage_evidence": [
                            evidence("input_tokens", 123, phase="partial", complete=True)
                        ],
                    }
                ],
            },
            {
                "label": "wrong_attempt",
                "at": at + timedelta(seconds=4),
                "settlement": "settled",
                "amount": "1",
                "attempts": [
                    {
                        "number": 1,
                        "attempt_id": str(uuid4()),
                        "evidence_version": 1,
                        "sent": True,
                        "usage_evidence": [
                            {
                                **evidence("input_tokens", 456),
                                "attempt_id": str(uuid4()),
                            }
                        ],
                    }
                ],
            },
            {
                "label": "wrong_metric_version",
                "at": at + timedelta(seconds=5),
                "settlement": "settled",
                "amount": "1",
                "attempts": [
                    {
                        "number": 1,
                        "evidence_version": 1,
                        "sent": True,
                        "usage_evidence": [
                            {
                                **evidence("input_tokens", 789),
                                "metric": "images",
                                "evidence_version": 2,
                            }
                        ],
                    }
                ],
            },
            {
                "label": "missing_upstream_terminal",
                "at": at + timedelta(seconds=6),
                "settlement": "settled",
                "amount": "1",
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "upstream_terminal": False,
                        "usage_evidence": [evidence("input_tokens", 321)],
                    }
                ],
            },
            {
                "label": "diagnostic",
                "at": at + timedelta(seconds=7),
                "source": "channel_diagnostic",
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "usage_evidence": [evidence("input_tokens", 7)],
                    }
                ],
            },
        ],
    )
    period = {
        "from": "2026-10-01T00:00:00+00:00",
        "to": "2026-10-02T00:00:00+00:00",
        "timezone": "UTC",
    }
    formal = await admin.api.get(SUMMARY, params=period)
    assert formal.status_code == 200, formal.text
    assert formal.json()["calls"] == 7
    bucket = next(
        item
        for item in formal.json()["metrics"]
        if item["metric"] == "tokens" and item["field"] == "input_tokens"
    )
    assert bucket["sum"] == "0" and bucket["known_calls"] == 0
    assert bucket["unknown_calls"] == 7
    diagnostic = await admin.api.get(SUMMARY, params={**period, "source": "diagnostic"})
    assert diagnostic.status_code == 200, diagnostic.text
    data = diagnostic.json()
    assert data["calls"] == 1 and data["settled_points"] is None
    assert data["amounts_by_currency"] == []
    assert data["current_held"]["applicable"] is False
    assert data["current_held"]["points"] is None
    assert data["current_held"]["scope"] is None
    assert (await admin.api.get(SUMMARY, params={**period, "source": "all"})).status_code == 422


async def test_management_queries_recheck_role_and_reject_key_only_access(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    ids, _, _ = await seed_calls(
        env,
        admin,
        member,
        [{"label": "visible", "at": datetime(2026, 10, 1, tzinfo=UTC), "settlement": "review"}],
    )
    detail_path = CALLS + "/" + str(ids["visible"])
    period = {"from": "2026-10-01T00:00:00+00:00", "to": "2026-10-02T00:00:00+00:00"}
    for path, params in ((CALLS, None), (detail_path, None), (SUMMARY, period)):
        assert (await member.api.get(path, params=params)).status_code == 403
        assert (await outsider.api.get(path, params=params)).status_code in (401, 403)
    assert (await admin.api.get(CALLS + "/" + str(uuid4()))).status_code == 404

    key_response = await admin.api.post(
        "/api/v1/account/access-keys",
        json={"creation_id": str(uuid4()), "name": "Query boundary"},
    )
    assert key_response.status_code == 200, key_response.text
    secret = key_response.json()["secret"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app),
        base_url="http://localhost",
        headers={"Authorization": "Bearer " + secret},
    ) as key_api:
        for path, params in ((CALLS, None), (detail_path, None), (SUMMARY, period)):
            assert (await key_api.get(path, params=params)).status_code == 401

    async with env.sessions() as db:
        actor = await db.get(Membership, admin.member.id)
        actor.role = "member"
        await db.commit()
    for path, params in ((CALLS, None), (detail_path, None), (SUMMARY, period)):
        assert (await admin.api.get(path, params=params)).status_code == 403


async def test_unpriced_raw_cache_is_visible_and_bad_old_price_cannot_break_detail(env):
    admin = await env.client()
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    ids, _, _ = await seed_calls(
        env,
        admin,
        admin,
        [
            {
                "label": "unpriced_cache",
                "at": at,
                "settlement": "review",
                "price": {"currency": "USD", "metric": "tokens", "input": "1"},
                "attempts": [
                    {
                        "number": 1,
                        "sent": True,
                        "usage_evidence": [
                            evidence("input_tokens", 100),
                            evidence("cache_read_tokens", 50),
                        ],
                    }
                ],
            },
            {
                "label": "bad_price",
                "at": at + timedelta(seconds=1),
                "settlement": "settled",
                "amount": "2",
                "attempts": [
                    {"number": 1, "sent": True, "usage_evidence": [evidence("input_tokens", 2)]}
                ],
            },
        ],
    )
    async with env.sessions() as db:
        row = await db.get(UsageSettlement, ids["bad_price"])
        row.price = {**row.price, "input": "not-a-decimal", "note": "DO_NOT_LEAK_SECRET"}
        await db.commit()
    period = {"from": "2026-10-01T00:00:00+00:00", "to": "2026-10-02T00:00:00+00:00"}
    summary = await admin.api.get(SUMMARY, params=period)
    assert summary.status_code == 200, summary.text
    bucket = next(
        item
        for item in summary.json()["metrics"]
        if item["metric"] == "tokens" and item["field"] == "cache_read_tokens"
    )
    assert bucket["sum"] == "50" and bucket["known_calls"] == 1
    detail = await admin.api.get(CALLS + "/" + str(ids["bad_price"]))
    assert detail.status_code == 200, detail.text
    assert "DO_NOT_LEAK_SECRET" not in detail.text
    assert detail.json()["settlement"]["budget_price"]["input"] is None


async def test_call_list_uses_server_pagination_and_independent_filters(env):
    admin = await env.client()
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    cases = [
        {
            "label": f"call_{number}",
            "at": at + timedelta(seconds=number),
            "settlement": "review" if number % 2 else "settled",
            "amount": "1" if number % 2 == 0 else None,
            "source": "desktop" if number % 2 else "access_key",
            "result": "succeeded" if number % 2 else "failed",
        }
        for number in range(21)
    ]
    ids, model_id, _ = await seed_calls(env, admin, admin, cases)
    first = await admin.api.get(CALLS)
    second = await admin.api.get(CALLS, params={"page": 2})
    assert first.status_code == second.status_code == 200
    assert first.json()["total"] == second.json()["total"] == 21
    assert first.json()["page_size"] == second.json()["page_size"] == 20
    assert len(first.json()["items"]) == 20 and len(second.json()["items"]) == 1
    assert {item["id"] for item in first.json()["items"]}.isdisjoint(
        {item["id"] for item in second.json()["items"]}
    )
    assert second.json()["items"][0]["id"] == str(ids["call_0"])
    filtered = await admin.api.get(
        CALLS,
        params={
            "source": "desktop",
            "model_id": str(model_id),
            "operation": "chat",
            "result_status": "success",
            "settlement_status": "review",
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["total"] == 10
    assert all(item["source"] == "desktop" for item in filtered.json()["items"])
    by_id = await admin.api.get(CALLS, params={"call_id": str(ids["call_3"])})
    assert by_id.status_code == 200
    assert [item["id"] for item in by_id.json()["items"]] == [str(ids["call_3"])]
