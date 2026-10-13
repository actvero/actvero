"""Pure evidence projection checks; API and isolation are tested separately."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.llm.call_queries import (
    CallFilters,
    accumulate_metrics,
    attempt_evidence,
    attempt_view,
    call_view,
    expected_fields,
    price_view,
    result_status,
    validate_filters,
    window_views,
)


def evidence(field: str, value: int, attempt_id: str, **overrides: object) -> dict[str, object]:
    metric = {
        "search_units": "searches",
        "input_characters": "characters",
        "image_count": "images",
    }.get(field, "tokens")
    return {
        "field": field,
        "value": value,
        "metric": metric,
        "source": "confirmed_delivery"
        if field == "image_count"
        else "validated_input"
        if field == "input_characters"
        else "upstream",
        "phase": "terminal",
        "complete": True,
        "attempt_id": attempt_id,
        "evidence_version": 1,
        **overrides,
    }


def attempt(attempt_id: str, *entries: dict[str, object]) -> dict[str, object]:
    return {
        "attempt_id": attempt_id,
        "sent": True,
        "upstream_terminal": True,
        "certainly_unused": False,
        "usage_evidence": list(entries),
        "usage": {"input_tokens": 999999},
    }


def buckets() -> dict[str, list[int]]:
    return {
        name: [0, 0, 0]
        for name in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_5m_tokens",
            "cache_write_1h_tokens",
            "input_characters",
            "search_units",
            "image_count",
        )
    }


def test_two_attempt_raw_usage_is_added_without_using_last_attempt_or_manual_usage():
    call = SimpleNamespace(
        kind="chat",
        attempts=[
            attempt(
                "one", evidence("input_tokens", 50, "one"), evidence("output_tokens", 5, "one")
            ),
            attempt(
                "two",
                evidence("input_tokens", 50, "two"),
                evidence("output_tokens", 15, "two"),
                evidence("cache_read_tokens", 3, "two"),
            ),
        ],
        usage={"input_tokens": 50, "output_tokens": 15},
    )
    settlement = SimpleNamespace(
        price={"metric": "tokens", "input": "1", "output": "2", "cache_read": None},
        usage={"input_tokens": 999, "output_tokens": 999, "cache_read_tokens": 999},
    )
    totals = buckets()
    accumulate_metrics(call, settlement, totals)
    assert totals["input_tokens"] == [100, 1, 0]
    assert totals["output_tokens"] == [20, 1, 0]
    # Actual but unpriced cache evidence is retained as an unknown whole-call quantity.
    assert "cache_read_tokens" in expected_fields(call, settlement)
    assert totals["cache_read_tokens"] == [0, 0, 1]


@pytest.mark.parametrize(
    "overrides",
    [
        {"source": "unknown"},
        {"phase": "partial"},
        {"metric": "characters"},
        {"attempt_id": "other"},
        {"evidence_version": 0},
    ],
)
def test_forged_or_partial_complete_flags_do_not_become_usage(overrides: dict[str, object]):
    entry = evidence("input_tokens", 10, "one")
    entry.update(overrides)
    row = attempt("one", entry)
    projected = attempt_evidence(row["usage_evidence"], attempt_id="one")
    assert len(projected) == 1 and projected[0].complete is False
    totals = buckets()
    accumulate_metrics(SimpleNamespace(kind="embedding", attempts=[row]), None, totals)
    assert totals["input_tokens"] == [0, 0, 1]


def test_conflicting_terminal_values_are_unknown_not_last_value():
    row = attempt("one", evidence("input_tokens", 10, "one"), evidence("input_tokens", 20, "one"))
    totals = buckets()
    accumulate_metrics(SimpleNamespace(kind="embedding", attempts=[row]), None, totals)
    assert totals["input_tokens"] == [0, 0, 1]


def test_upstream_not_terminal_is_unknown_but_proven_unsent_is_zero():
    partial = attempt("one", evidence("input_tokens", 10, "one"))
    partial["upstream_terminal"] = False
    totals = buckets()
    accumulate_metrics(SimpleNamespace(kind="embedding", attempts=[partial]), None, totals)
    assert totals["input_tokens"] == [0, 0, 1]
    unsent = {"sent": False, "certainly_unused": True}
    totals = buckets()
    accumulate_metrics(SimpleNamespace(kind="embedding", attempts=[unsent]), None, totals)
    assert totals["input_tokens"] == [0, 1, 0]


def test_character_search_and_image_evidence_preserve_distinct_sources():
    for kind, field, metric in (
        ("embedding", "input_characters", "characters"),
        ("rerank", "search_units", "searches"),
        ("image_generation", "image_count", "images"),
    ):
        row = attempt("one", evidence(field, 7, "one"))
        projected = attempt_view(row)
        assert projected is not None
        assert projected.usage_evidence[0].metric == metric
        assert projected.usage_evidence[0].complete is True
        totals = buckets()
        settlement = SimpleNamespace(
            price={"metric": "search_units" if kind == "rerank" else metric}
        )
        accumulate_metrics(SimpleNamespace(kind=kind, attempts=[row]), settlement, totals)
        assert totals[field] == [7, 1, 0]


def test_snapshot_projection_whitelists_price_window_and_attempt_metadata():
    assert (
        price_view(
            {
                "metric": "tokens",
                "currency": "USD",
                "unit": 1000000,
                "input": "1.25",
                "secret": "do-not-return",
                "cache_read": "bad decimal",
            }
        ).model_dump()["cache_read"]
        is None
    )
    assert price_view({"metric": "tokens", "currency": "USD", "unit": 0}) is None
    windows = window_views(
        {
            "windows": [
                {
                    "rule": {"kind": "fixed_hours", "points": "100", "hours": 24, "key": "secret"},
                    "used": "2",
                    "remaining": "98",
                    "secret": "do-not-return",
                }
            ]
        }
    )
    assert len(windows) == 1 and "secret" not in windows[0].model_dump()
    projected = attempt_view({"attempt_id": "one", "secret": "do-not-return"})
    assert projected is not None and "secret" not in projected.model_dump()


def test_withheld_success_is_interrupted_and_sparse_legacy_remains_unknown():
    assert (
        result_status(
            SimpleNamespace(status="succeeded", termination_code="access_changed", error_code=None)
        )
        == "interrupted"
    )
    call = SimpleNamespace(
        id=uuid4(),
        created_at=datetime.now(UTC),
        model_id=None,
        kind="chat",
        source="channel_diagnostic",
        status="pending",
        error_code=None,
        termination_code=None,
        attempts=[{}],
        duration_ms=None,
    )
    view = call_view(call, None, None, None, None)
    assert view.result_status == "unknown"
    assert view.settlement_status == "not_applicable"
    assert view.points is None and view.reserved_points is None


def test_half_open_range_and_held_scope_validation():
    now = datetime.now(UTC)
    tenant_id = uuid4()
    validate_filters(
        CallFilters(
            tenant_id=tenant_id,
            from_time=now - timedelta(days=90),
            to_time=now,
            timezone_name="Asia/Shanghai",
        )
    )
    with pytest.raises(HTTPException) as too_long:
        validate_filters(
            CallFilters(
                tenant_id=tenant_id,
                from_time=now - timedelta(days=90, seconds=1),
                to_time=now,
            )
        )
    assert too_long.value.status_code == 422
    with pytest.raises(HTTPException):
        validate_filters(CallFilters(tenant_id=tenant_id, held=True, result_status="success"))
    with pytest.raises(HTTPException):
        validate_filters(CallFilters(tenant_id=tenant_id), summary=True)
