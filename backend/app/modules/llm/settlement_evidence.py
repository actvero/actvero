"""Conservative, pure automatic settlement decision from persisted attempt evidence.

This module never performs ledger mutations or manual reconciliation. A review
decision is sticky for the caller: later SDK callbacks cannot silently settle it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.modules.llm.catalog_schemas import TokenPrice

Action = Literal["settle", "review", "release"]
_CACHE = ("cache_read_tokens", "cache_write_5m_tokens", "cache_write_1h_tokens")
_RAW_INPUT_TOTAL = ("raw_prompt_tokens", "raw_prompt_token_count")
_RAW_INPUT_NET = "raw_input_tokens"
_MAX_ATTEMPTS = 64
_CANONICAL = {
    "input_tokens": "upstream",
    "output_tokens": "upstream",
    "cache_read_tokens": "upstream",
    "cache_write_5m_tokens": "upstream",
    "cache_write_1h_tokens": "upstream",
    "search_units": "upstream",
    "input_characters": "validated_input",
    "image_count": "confirmed_delivery",
    "audio_duration_ms": "validated_input",
}
_FIELD_METRIC = {
    "input_tokens": "tokens",
    "output_tokens": "tokens",
    "cache_read_tokens": "tokens",
    "cache_write_5m_tokens": "tokens",
    "cache_write_1h_tokens": "tokens",
    "raw_prompt_tokens": "tokens",
    "raw_prompt_token_count": "tokens",
    "raw_input_tokens": "tokens",
    "raw_completion_tokens": "tokens",
    "raw_output_tokens": "tokens",
    "raw_candidates_token_count": "tokens",
    "raw_thoughts_token_count": "tokens",
    "input_characters": "characters",
    "search_units": "searches",
    "image_count": "images",
    "audio_duration_ms": "seconds",
}


@dataclass(frozen=True, slots=True)
class SettlementDecision:
    action: Action
    usage: dict[str, int]
    reason: str
    metadata: dict[str, Any]


def observed_usage(attempts: list[dict[str, Any]]) -> dict[str, int]:
    """Last attempt's canonical observations for review display, never billing."""
    if not isinstance(attempts, list) or not attempts or not isinstance(attempts[-1], dict):
        return {}
    last = attempts[-1]
    attempt_id = last.get("attempt_id")
    evidence = last.get("usage_evidence")
    if not isinstance(attempt_id, str) or not isinstance(evidence, list):
        return {}
    candidates: dict[str, dict[int, set[int]]] = {}
    for item in evidence:
        if not isinstance(item, dict):
            continue
        field = item.get("field")
        if not isinstance(field, str) or field not in _CANONICAL:
            continue
        if (
            item.get("attempt_id") != attempt_id
            or item.get("evidence_version") != 1
            or item.get("source") != _CANONICAL[field]
            or item.get("metric") != _FIELD_METRIC[field]
            or not _integer(item.get("value"))
        ):
            continue
        phase = item.get("phase")
        if not isinstance(phase, str) or phase not in {
            "partial",
            "terminal",
            "validated_input",
            "confirmed_delivery",
        }:
            continue
        if _CANONICAL[field] == "upstream" and phase not in {"partial", "terminal"}:
            continue
        if _CANONICAL[field] == "validated_input" and phase not in {"terminal", "validated_input"}:
            continue
        if _CANONICAL[field] == "confirmed_delivery" and phase not in {
            "terminal",
            "confirmed_delivery",
        }:
            continue
        rank = 2 if phase != "partial" and item.get("complete") is True else 1
        candidates.setdefault(field, {1: set(), 2: set()})[rank].add(item["value"])
    projected: dict[str, int] = {}
    for field, ranks in candidates.items():
        chosen = ranks[2] if ranks[2] else ranks[1]
        if len(chosen) == 1:
            projected[field] = next(iter(chosen))
    return projected


def _integer(value: Any) -> bool:
    return type(value) is int and 0 <= value <= 10**12


def _safe_metadata(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Whitelist identifiers and measured numbers; omit request/provider payloads."""
    rows: list[dict[str, Any]] = []
    for attempt in attempts[:_MAX_ATTEMPTS]:
        if not isinstance(attempt, dict):
            continue
        attempt_id = attempt.get("attempt_id")
        status = attempt.get("status")
        row: dict[str, Any] = {
            "attempt_id": attempt_id
            if isinstance(attempt_id, str) and len(attempt_id) <= 128
            else None,
            "sent": attempt.get("sent") if type(attempt.get("sent")) is bool else None,
            "status": status
            if isinstance(status, str) and status in {"pending", "succeeded", "failed", "unknown"}
            else "unknown",
            "upstream_terminal": attempt.get("upstream_terminal") is True,
            "uncertain": attempt.get("uncertain") is True,
            "fields": [],
        }
        evidence = attempt.get("usage_evidence")
        if isinstance(evidence, list):
            for item in evidence[:32]:
                if not isinstance(item, dict):
                    continue
                field = item.get("field")
                if not isinstance(field, str) or field not in {
                    "input_tokens",
                    "output_tokens",
                    "input_characters",
                    "search_units",
                    "image_count",
                    "audio_duration_ms",
                    *_CACHE,
                    *_RAW_INPUT_TOTAL,
                    _RAW_INPUT_NET,
                    "raw_completion_tokens",
                    "raw_output_tokens",
                    "raw_candidates_token_count",
                    "raw_thoughts_token_count",
                }:
                    continue
                source = item.get("source")
                phase = item.get("phase")
                row["fields"].append(
                    {
                        "field": field,
                        "value": item.get("value") if _integer(item.get("value")) else None,
                        "metric": item.get("metric")
                        if item.get("metric") == _FIELD_METRIC[field]
                        else "unknown",
                        "source": source
                        if isinstance(source, str)
                        and source in {"upstream", "validated_input", "confirmed_delivery"}
                        else "unknown",
                        "evidence_version": item.get("evidence_version")
                        if item.get("evidence_version") == 1
                        else None,
                        "complete": item.get("complete") is True,
                        "phase": phase
                        if isinstance(phase, str)
                        and phase
                        in {"partial", "terminal", "validated_input", "confirmed_delivery"}
                        else "unknown",
                    }
                )
        rows.append(row)
    return {"evidence_version": 1, "attempts": rows, "assumptions": []}


def _field(attempt: dict[str, Any], field: str, source: str) -> tuple[int | None, bool]:
    """Return one complete terminal value and whether conflicting evidence exists."""
    evidence = attempt.get("usage_evidence")
    if not isinstance(evidence, list):
        return None, False
    values: set[int] = set()
    attempt_id = attempt.get("attempt_id")
    for item in evidence:
        if not isinstance(item, dict) or item.get("field") != field:
            continue
        phase = item.get("phase")
        if (
            item.get("attempt_id") != attempt_id
            or item.get("evidence_version") != 1
            or item.get("metric") != _FIELD_METRIC[field]
            or item.get("source") != source
            or item.get("complete") is not True
            or not isinstance(phase, str)
            or phase
            not in (
                {"terminal"}
                if source == "upstream"
                else {"terminal", "validated_input"}
                if source == "validated_input"
                else {"terminal", "confirmed_delivery"}
            )
            or not _integer(item.get("value"))
        ):
            continue
        values.add(item["value"])
    return (next(iter(values)) if len(values) == 1 else None), len(values) > 1


def _token_usage(
    price: TokenPrice, attempt: dict[str, Any], metadata: dict[str, Any]
) -> tuple[dict[str, int] | None, str]:
    inp, conflict = _field(attempt, "input_tokens", "upstream")
    if conflict:
        return None, "evidence_conflict"
    if inp is None:
        return None, "input_tokens_missing"
    output, conflict = _field(attempt, "output_tokens", "upstream")
    if conflict:
        return None, "evidence_conflict"
    if price.output is not None and output is None:
        return None, "output_tokens_missing"
    if price.output is None and output not in (None, 0):
        return None, "output_tokens_unpriced"
    if output is not None:
        for raw_field in ("raw_completion_tokens", "raw_output_tokens"):
            raw_output, conflict = _field(attempt, raw_field, "upstream")
            if conflict:
                return None, "evidence_conflict"
            if raw_output is not None and raw_output != output:
                return None, "output_tokens_mismatch"
        candidates, candidate_conflict = _field(attempt, "raw_candidates_token_count", "upstream")
        thoughts, thought_conflict = _field(attempt, "raw_thoughts_token_count", "upstream")
        if candidate_conflict or thought_conflict:
            return None, "evidence_conflict"
        if candidates is not None and output != candidates + (thoughts or 0):
            return None, "output_tokens_mismatch"
    usage = {"input_tokens": inp}
    if output is not None:
        usage["output_tokens"] = output
    explicit: dict[str, int] = {}
    for field, rate_name in zip(
        _CACHE, ("cache_read", "cache_write_5m", "cache_write_1h"), strict=True
    ):
        count, conflict = _field(attempt, field, "upstream")
        if conflict:
            return None, "evidence_conflict"
        rate = getattr(price, rate_name)
        if rate is not None and count is None:
            return None, "priced_cache_missing"
        if rate is None and count is not None and count > 0:
            return None, "unpriced_cache_positive"
        if count is not None:
            explicit[field] = count
            usage[field] = count
    # If a provider supplied a total, it must reconcile with the normalized net
    # input and explicit cache buckets. Missing unpriced buckets are then known
    # to contribute nothing to this decomposition, without calling them raw 0.
    totals = [_field(attempt, field, "upstream") for field in _RAW_INPUT_TOTAL]
    if any(conflict for _, conflict in totals):
        return None, "evidence_conflict"
    known_totals = [value for value, _ in totals if value is not None]
    net, conflict = _field(attempt, _RAW_INPUT_NET, "upstream")
    if conflict:
        return None, "evidence_conflict"
    if known_totals and any(total != inp + sum(explicit.values()) for total in known_totals):
        return None, "cache_decomposition_mismatch"
    if net is not None and net != inp:
        return None, "cache_decomposition_mismatch"
    if (
        len(explicit) < len(_CACHE)
        and not known_totals
        and net is None
        and price.output is not None
    ):
        return None, "cache_decomposition_unknown"
    for field in _CACHE:
        if field not in usage:
            metadata["assumptions"].append(
                {
                    "attempt_id": attempt["attempt_id"],
                    "field": field,
                    "kind": "unpriced_omitted",
                }
            )
    return usage, "verified_usage"


def _auxiliary_usage(
    price: TokenPrice, sent_attempts: list[dict[str, Any]], priced: dict[str, int]
) -> tuple[dict[str, int], list[str]]:
    """Retain non-priced complete meters only when every sent attempt agrees."""
    primary = {
        "tokens": "input_tokens",
        "characters": "input_characters",
        "search_units": "search_units",
        "images": "image_count",
        "seconds": "audio_duration_ms",
    }[price.metric]
    billable = {primary}
    if price.output is not None:
        billable.update(("output_tokens", *_CACHE))
    auxiliary: dict[str, int] = {}
    for field, source in _CANONICAL.items():
        if field in priced or field in billable:
            continue
        values: list[int] = []
        for attempt in sent_attempts:
            value, conflict = _field(attempt, field, source)
            if conflict or value is None:
                break
            values.append(value)
        else:
            auxiliary[field] = sum(values)
    return auxiliary, sorted(auxiliary)


def evaluate(
    price: TokenPrice, attempts: list[dict[str, Any]], *, delivered: bool
) -> SettlementDecision:
    """Decide automatic settlement from every attempt, never SDK-computed usage.

    `delivered` means validated billable output (including controlled media
    acquisition), before a later authorization or client-send decision. It is
    not an inference from HTTP 200 or a client-terminal flag.
    """
    safe_attempts = attempts if isinstance(attempts, list) else []
    metadata = _safe_metadata(safe_attempts)

    def decision(
        action: Action, reason: str, usage: dict[str, int] | None = None
    ) -> SettlementDecision:
        if action == "review" and usage is None:
            usage = observed_usage(safe_attempts)
        return SettlementDecision(
            action,
            usage or {},
            reason,
            {
                **metadata,
                "decision": action,
                "reason": reason,
                "metric": price.metric,
                "usage_scope": "last_attempt_observed"
                if action == "review"
                else "all_confirmed_attempts"
                if action == "settle"
                else "no_send",
            },
        )

    if not safe_attempts:
        return decision("review", "attempts_missing")
    if len(safe_attempts) > _MAX_ATTEMPTS or any(not isinstance(a, dict) for a in safe_attempts):
        return decision("review", "attempts_invalid")
    ids = [a.get("attempt_id") for a in safe_attempts]
    if any(not isinstance(value, str) or not value or len(value) > 128 for value in ids):
        return decision("review", "attempt_identity_missing")
    if len(set(ids)) != len(ids):
        return decision("review", "attempt_identity_conflict")
    if any(a.get("evidence_version") != 1 for a in safe_attempts):
        return decision("review", "attempt_version_unknown")
    if all(a.get("sent") is False for a in safe_attempts):
        if delivered or any(a.get("status") == "succeeded" for a in safe_attempts):
            return decision("review", "delivery_conflicts_with_no_send")
        return decision("release", "all_attempts_not_sent")
    if any(a.get("sent") is not True and a.get("sent") is not False for a in safe_attempts):
        return decision("review", "send_unknown")
    if not delivered:
        return decision("review", "delivery_unconfirmed")
    total: dict[str, int] = {}
    for attempt in safe_attempts:
        if attempt["sent"] is False:
            continue
        status = attempt.get("status")
        if (
            not isinstance(status, str)
            or status not in {"succeeded", "failed"}
            or attempt.get("uncertain") is not False
        ):
            return decision("review", "execution_unknown")
        if price.metric in {"characters", "images", "seconds"} and status != "succeeded":
            return decision("review", "execution_unknown")
        if price.metric == "tokens":
            if attempt.get("upstream_terminal") is not True:
                return decision("review", "upstream_terminal_missing")
            values, reason = _token_usage(price, attempt, metadata)
            if values is None:
                return decision("review", reason)
        else:
            field, source = {
                "characters": ("input_characters", "validated_input"),
                "search_units": ("search_units", "upstream"),
                "images": ("image_count", "confirmed_delivery"),
                "seconds": ("audio_duration_ms", "validated_input"),
            }[price.metric]
            if (
                price.metric in {"search_units", "seconds"}
                and attempt.get("upstream_terminal") is not True
            ):
                return decision("review", "upstream_terminal_missing")
            count, conflict = _field(attempt, field, source)
            if conflict:
                return decision("review", "evidence_conflict")
            if count is None:
                return decision("review", "usage_missing")
            values = {field: count}
        for field, count in values.items():
            total[field] = total.get(field, 0) + count
    # settlement.py imports this evaluator; import arithmetic only on demand.
    from app.modules.llm.settlement import amount_for

    if not total or amount_for(price, total) is None:
        return decision("review", "amount_unavailable")
    auxiliary, fields = _auxiliary_usage(
        price, [attempt for attempt in safe_attempts if attempt["sent"] is True], total
    )
    if fields:
        metadata["auxiliary_fields"] = fields
        total.update(auxiliary)
    return decision("settle", "verified_usage", total)
