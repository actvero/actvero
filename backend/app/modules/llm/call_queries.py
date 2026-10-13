"""Bounded, tenant-scoped ModelCall queries and evidence-only projections."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import Select, String, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent
from app.modules.llm.call_schemas import (
    AmountBucket,
    CallAttemptView,
    CallAuditView,
    CallDetail,
    CallPage,
    CallSettlementView,
    CurrentHeld,
    DistributionBucket,
    HeldScope,
    LogicalCallView,
    MetricBucket,
    PolicySnapshotView,
    PriceSnapshotView,
    SummaryRange,
    UsageEvidenceView,
    UsageSummary,
    WindowSnapshotView,
)
from app.modules.llm.models import CatalogModel, ModelCall, ModelChannel, UsageSettlement
from app.modules.llm.points import decimal_text
from app.modules.members.models import Membership
from app.modules.users.models import User

FORMAL = ("access_key", "desktop")
DIAGNOSTIC = ("admin_channel_test", "admin_route_test", "channel_diagnostic")
RESULTS = ("success", "failed", "interrupted", "cancelled", "unknown")
SETTLEMENTS = ("reserved", "review", "settled", "released", "not_applicable")
WITHHELD_RESULTS = ("access_changed", "configuration_changed", "model_unavailable")
FIELDS = {
    "tokens": (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_5m_tokens",
        "cache_write_1h_tokens",
    ),
    "characters": ("input_characters",),
    "search_units": ("search_units",),
    "images": ("image_count",),
    "seconds": ("audio_duration_ms",),
}
PRICE_FIELDS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_tokens": "cache_read",
    "cache_write_5m_tokens": "cache_write_5m",
    "cache_write_1h_tokens": "cache_write_1h",
}
SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class CallFilters:
    tenant_id: UUID
    from_time: datetime | None = None
    to_time: datetime | None = None
    timezone_name: str = "UTC"
    member_id: UUID | None = None
    model_id: UUID | None = None
    operation: str | None = None
    source: str = "member"
    result_status: str | None = None
    settlement_status: str | None = None
    call_id: UUID | None = None
    held: bool = False
    channel_id: UUID | None = None
    unknown_channel: bool = False


def validate_filters(filters: CallFilters, *, summary: bool = False) -> None:
    try:
        ZoneInfo(filters.timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, "请选择有效的 IANA 时区") from exc
    if (filters.from_time is None) != (filters.to_time is None) or (
        summary and filters.from_time is None
    ):
        raise HTTPException(422, "开始与结束时间须同时填写")
    if filters.from_time is not None and filters.to_time is not None:
        start, end = filters.from_time, filters.to_time
        if start.utcoffset() is None or end.utcoffset() is None:
            raise HTTPException(422, "时间必须包含时区偏移")
        if not start < end or end - start > timedelta(days=90):
            raise HTTPException(422, "时间区间必须大于零且不超过90天")
    if filters.channel_id is not None and filters.unknown_channel:
        raise HTTPException(422, "最终渠道筛选不能同时指定未知与渠道编号")
    if filters.source not in ("member", "desktop", "access_key", "diagnostic", "all"):
        raise HTTPException(422, "来源筛选无效")
    if summary and filters.source == "all":
        raise HTTPException(422, "统计须单独选择正式调用或诊断")
    if filters.result_status is not None and filters.result_status not in RESULTS:
        raise HTTPException(422, "结果状态无效")
    if filters.settlement_status is not None:
        values = filters.settlement_status.split(",")
        if (
            not values
            or len(set(values)) != len(values)
            or any(value not in SETTLEMENTS for value in values)
        ):
            raise HTTPException(422, "结算状态无效")
    if filters.held and (
        filters.source in ("all", "diagnostic")
        or filters.from_time is not None
        or filters.result_status is not None
        or filters.settlement_status is not None
        or filters.call_id is not None
        or filters.channel_id is not None
        or filters.unknown_channel
    ):
        raise HTTPException(422, "当前占用明细只能按成员、模型、操作和正式来源筛选")


def result_expression() -> Any:
    return case(
        (
            (ModelCall.error_code == "caller_cancelled")
            | (ModelCall.termination_code == "caller_cancelled"),
            "cancelled",
        ),
        (ModelCall.termination_code.in_((*WITHHELD_RESULTS, "stream_started")), "interrupted"),
        (ModelCall.status == "succeeded", "success"),
        (ModelCall.status == "failed", "failed"),
        else_="unknown",
    )


def result_status(call: ModelCall) -> str:
    if call.error_code == "caller_cancelled" or call.termination_code == "caller_cancelled":
        return "cancelled"
    if call.termination_code in (*WITHHELD_RESULTS, "stream_started"):
        return "interrupted"
    if call.status == "succeeded":
        return "success"
    if call.status == "failed":
        return "failed"
    return "unknown"


def final_channel_expression() -> Any:
    last = ModelCall.attempts[-1]
    channel = last["channel_id"].astext
    valid_channel = (
        select(ModelChannel.id.cast(String))
        .where(ModelChannel.tenant_id == ModelCall.tenant_id)
        .correlate(ModelCall)
    )
    return case(
        (
            (last["evidence_version"] == literal(1, type_=ModelCall.attempts.type))
            & (last["evidence_version"].astext == "1")
            & (last["sent"] == literal(True, type_=ModelCall.attempts.type))
            & (last["upstream_terminal"] == literal(True, type_=ModelCall.attempts.type))
            & last["status"].astext.in_(("succeeded", "failed"))
            & channel.in_(valid_channel),
            channel,
        ),
        else_=None,
    )


def where_calls(stmt: Select[Any], filters: CallFilters) -> Select[Any]:
    stmt = stmt.where(ModelCall.tenant_id == filters.tenant_id)
    if filters.source == "member":
        stmt = stmt.where(ModelCall.source.in_(FORMAL))
    elif filters.source == "diagnostic":
        stmt = stmt.where(ModelCall.source.in_(DIAGNOSTIC))
    elif filters.source != "all":
        stmt = stmt.where(ModelCall.source == filters.source)
    if filters.from_time is not None and filters.to_time is not None:
        stmt = stmt.where(
            ModelCall.created_at >= filters.from_time,
            ModelCall.created_at < filters.to_time,
        )
    if filters.member_id is not None:
        diagnostic_actor = select(Membership.user_id).where(
            Membership.tenant_id == filters.tenant_id,
            Membership.id == filters.member_id,
        )
        stmt = stmt.where(
            or_(
                UsageSettlement.member_id == filters.member_id,
                ((ModelCall.source.in_(DIAGNOSTIC)) | UsageSettlement.id.is_(None))
                & (ModelCall.actor_id.in_(diagnostic_actor)),
            )
        )
    if filters.model_id is not None:
        stmt = stmt.where(ModelCall.model_id == filters.model_id)
    if filters.operation is not None:
        stmt = stmt.where(ModelCall.kind == filters.operation)
    if filters.result_status is not None:
        stmt = stmt.where(result_expression() == filters.result_status)
    if filters.settlement_status is not None:
        statuses = filters.settlement_status.split(",")
        if "not_applicable" in statuses:
            selected = [s for s in statuses if s != "not_applicable"]
            condition = (
                or_(UsageSettlement.id.is_(None), UsageSettlement.status.in_(selected))
                if selected
                else UsageSettlement.id.is_(None)
            )
            stmt = stmt.where(condition)
        else:
            stmt = stmt.where(UsageSettlement.status.in_(statuses))
    if filters.held:
        stmt = stmt.where(UsageSettlement.status.in_(("reserved", "review")))
    if filters.channel_id is not None:
        stmt = stmt.where(final_channel_expression() == str(filters.channel_id))
    elif filters.unknown_channel:
        stmt = stmt.where(final_channel_expression().is_(None))
    if filters.call_id is not None:
        stmt = stmt.where(ModelCall.id == filters.call_id)
    return stmt


def base_rows() -> Select[Any]:
    return (
        select(ModelCall, UsageSettlement, CatalogModel, Membership, User)
        .outerjoin(UsageSettlement, UsageSettlement.id == ModelCall.id)
        .outerjoin(CatalogModel, CatalogModel.id == ModelCall.model_id)
        .outerjoin(
            Membership,
            (Membership.user_id == ModelCall.actor_id)
            & (Membership.tenant_id == ModelCall.tenant_id),
        )
        .outerjoin(User, User.id == ModelCall.actor_id)
    )


def safe_code(value: Any) -> str | None:
    return value if isinstance(value, str) and SAFE_CODE.fullmatch(value) else None


def safe_count(value: Any) -> int | None:
    return value if type(value) is int and 0 <= value <= 10**12 else None


def safe_uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value)) if value is not None else None
    except (ValueError, AttributeError):
        return None


def safe_name(value: Any, *, length: int = 200) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) > length
        or any(char in value for char in ("\n", "\r", "\x00", "@", "://"))
    ):
        return None
    return value


def safe_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.utcoffset() is not None else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.utcoffset() is not None else None
        except ValueError:
            return None
    return None


def safe_decimal(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
        return decimal_text(number) if number.is_finite() and number >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def attempt_evidence(raw: Any, *, attempt_id: str | None = None) -> list[UsageEvidenceView]:
    if not isinstance(raw, list):
        return []
    result: list[UsageEvidenceView] = []
    for entry in raw[:100]:
        if not isinstance(entry, dict):
            continue
        field = entry.get("field")
        if field not in {name for names in FIELDS.values() for name in names}:
            continue
        metric = next(name for name, names in FIELDS.items() if field in names)
        evidence_metric = "searches" if metric == "search_units" else metric
        source = entry.get("source")
        phase = entry.get("phase")
        value = safe_count(entry.get("value"))
        allowed = (
            (metric in ("tokens", "search_units") and source == "upstream" and phase == "terminal")
            or (
                metric in {"characters", "seconds"}
                and source == "validated_input"
                and phase in ("validated_input", "terminal")
            )
            or (
                metric == "images"
                and source == "confirmed_delivery"
                and phase in ("confirmed_delivery", "terminal")
            )
        )
        allowed = (
            allowed
            and entry.get("metric") == evidence_metric
            and entry.get("evidence_version") == 1
            and attempt_id is not None
            and entry.get("attempt_id") == attempt_id
        )
        result.append(
            UsageEvidenceView(
                field=field,
                value=value,
                metric=evidence_metric,
                source=source
                if source in ("upstream", "unknown", "validated_input", "confirmed_delivery")
                else "unknown",
                complete=entry.get("complete") is True and value is not None and allowed,
                phase=phase
                if phase in ("partial", "terminal", "validated_input", "confirmed_delivery")
                else "unknown",
                attempt_id=safe_name(entry.get("attempt_id"), length=128),
                evidence_version=safe_count(entry.get("evidence_version")),
            )
        )
    return result


def attempt_view(raw: Any) -> CallAttemptView | None:
    if not isinstance(raw, dict):
        return None
    return CallAttemptView(
        number=safe_count(raw.get("number")),
        attempt_id=safe_name(raw.get("attempt_id"), length=128),
        evidence_version=safe_count(raw.get("evidence_version")),
        operation=safe_code(raw.get("operation")),
        binding_id=safe_uuid(raw.get("binding_id")),
        channel_id=safe_uuid(raw.get("channel_id")),
        channel_name=safe_name(raw.get("channel_name")),
        upstream_id=safe_name(raw.get("upstream_id")),
        config_version=safe_count(raw.get("config_version")),
        channel_version=safe_count(raw.get("channel_version")),
        started_at=safe_datetime(raw.get("started_at")),
        status=safe_code(raw.get("status")),
        sent=raw.get("sent") if type(raw.get("sent")) is bool else None,
        output_started=raw.get("output_started")
        if type(raw.get("output_started")) is bool
        else None,
        first_output_ms=safe_count(raw.get("first_output_ms")),
        upstream_terminal=raw.get("upstream_terminal")
        if type(raw.get("upstream_terminal")) is bool
        else None,
        client_terminal=raw.get("client_terminal")
        if type(raw.get("client_terminal")) is bool
        else None,
        upstream_status=safe_count(raw.get("upstream_status")),
        retry_after_seconds=safe_count(raw.get("retry_after_seconds")),
        retry_reason=safe_code(raw.get("retry_reason")),
        error_code=safe_code(raw.get("error_code")),
        error_scope=safe_code(raw.get("error_scope")),
        retryable_hint=raw.get("retryable_hint")
        if type(raw.get("retryable_hint")) is bool
        else None,
        uncertain=raw.get("uncertain") if type(raw.get("uncertain")) is bool else None,
        certainly_unused=raw.get("certainly_unused")
        if type(raw.get("certainly_unused")) is bool
        else None,
        duration_ms=safe_count(raw.get("duration_ms")),
        usage_evidence=attempt_evidence(
            raw.get("usage_evidence"), attempt_id=safe_name(raw.get("attempt_id"), length=128)
        ),
        budget_price=price_view(raw.get("prices", {}).get("budget"))
        if isinstance(raw.get("prices"), dict)
        else None,
        procurement_price=price_view(raw.get("prices", {}).get("procurement"))
        if isinstance(raw.get("prices"), dict)
        else None,
        budget_estimate=safe_decimal(raw.get("estimates", {}).get("budget"))
        if isinstance(raw.get("estimates"), dict)
        else None,
        procurement_estimate=safe_decimal(raw.get("estimates", {}).get("procurement"))
        if isinstance(raw.get("estimates"), dict)
        else None,
    )


def call_view(
    call: ModelCall,
    settlement: UsageSettlement | None,
    model: CatalogModel | None,
    actor_membership: Membership | None,
    member_user: User | None,
) -> LogicalCallView:
    with localcontext() as ctx:
        ctx.prec = 80
        points = (
            decimal_text(settlement.amount * settlement.ratio)
            if settlement is not None and settlement.amount is not None
            else None
        )
        reserved_points = (
            decimal_text(settlement.reserved_amount * settlement.ratio)
            if settlement is not None
            else None
        )
    return LogicalCallView(
        id=call.id,
        created_at=call.created_at,
        model_id=call.model_id,
        model_name=model.name if model else None,
        member_id=settlement.member_id
        if settlement
        else actor_membership.id
        if actor_membership
        else None,
        member_name=member_user.name if member_user else None,
        operation=call.kind,
        source=call.source,
        result_status=cast(Any, result_status(call)),
        settlement_status=cast(Any, settlement.status if settlement else "not_applicable"),
        attempt_count=len(call.attempts) if isinstance(call.attempts, list) else 0,
        duration_ms=call.duration_ms,
        terminal_reason=safe_code(call.termination_code),
        points=points,
        reserved_points=reserved_points,
    )


def price_view(raw: Any) -> PriceSnapshotView | None:
    if not isinstance(raw, dict):
        return None
    metric = raw.get("metric")
    currency = raw.get("currency")
    unit = safe_count(raw.get("unit"))
    if (
        metric not in FIELDS
        or not isinstance(currency, str)
        or not re.fullmatch(r"[A-Z]{3}", currency)
        or unit is None
        or unit == 0
    ):
        return None
    return PriceSnapshotView(
        metric=metric,
        currency=currency,
        unit=unit,
        input=safe_decimal(raw.get("input")),
        output=safe_decimal(raw.get("output")),
        cache_read=safe_decimal(raw.get("cache_read")),
        cache_write_5m=safe_decimal(raw.get("cache_write_5m")),
        cache_write_1h=safe_decimal(raw.get("cache_write_1h")),
    )


def policy_view(raw: Any) -> PolicySnapshotView | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("policy"), dict):
        return None
    policy = raw["policy"]
    return PolicySnapshotView(
        id=safe_uuid(policy.get("id")),
        name=safe_name(policy.get("name")),
        version=safe_count(policy.get("version")),
    )


def window_views(raw: Any) -> list[WindowSnapshotView]:
    if not isinstance(raw, dict) or not isinstance(raw.get("windows"), list):
        return []
    result: list[WindowSnapshotView] = []
    for window in raw["windows"][:20]:
        if not isinstance(window, dict):
            continue
        rule: dict[str, Any] = window["rule"] if isinstance(window.get("rule"), dict) else {}
        result.append(
            WindowSnapshotView(
                kind=safe_code(rule.get("kind")),
                points=safe_decimal(rule.get("points")),
                hours=safe_count(rule.get("hours")),
                timezone=safe_name(rule.get("timezone"), length=100),
                week_start=safe_count(rule.get("week_start")),
                used=safe_decimal(window.get("used")),
                reserved=safe_decimal(window.get("reserved")),
                remaining=safe_decimal(window.get("remaining")),
                started_at=safe_datetime(window.get("started_at")),
                resets_at=safe_datetime(window.get("resets_at")),
            )
        )
    return result


def settlement_view(row: UsageSettlement) -> CallSettlementView:
    with localcontext() as ctx:
        ctx.prec = 80
        return CallSettlementView(
            id=row.id,
            status=cast(Any, row.status),
            version=row.version,
            currency=row.currency,
            ratio=decimal_text(row.ratio),
            reserved_amount=decimal_text(row.reserved_amount),
            amount=decimal_text(row.amount) if row.amount is not None else None,
            reserved_points=decimal_text(row.reserved_amount * row.ratio),
            points=decimal_text(row.amount * row.ratio) if row.amount is not None else None,
            created_at=row.created_at,
            settled_at=row.settled_at,
            budget_price=price_view(row.price),
            conversion_id=row.conversion_id,
            policy=policy_view(row.policy_snapshot),
            windows=window_views(row.policy_snapshot),
        )


async def call_page(db: AsyncSession, filters: CallFilters, page: int) -> CallPage:
    validate_filters(filters)
    count_query = select(func.count(ModelCall.id)).outerjoin(
        UsageSettlement, UsageSettlement.id == ModelCall.id
    )
    count_query = where_calls(count_query, filters)
    total = await db.scalar(count_query) or 0
    rows = await db.execute(
        where_calls(base_rows(), filters)
        .order_by(ModelCall.created_at.desc(), ModelCall.id.desc())
        .limit(20)
        .offset((page - 1) * 20)
    )
    return CallPage(items=[call_view(*row) for row in rows.all()], total=total, page=page)


async def call_detail(db: AsyncSession, tenant_id: UUID, call_id: UUID) -> CallDetail:
    row = (
        await db.execute(
            base_rows().where(ModelCall.tenant_id == tenant_id, ModelCall.id == call_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "调用记录不存在")
    call, settlement, model, actor_membership, member_user = row
    attempts = [view for raw in call.attempts or [] if (view := attempt_view(raw))]
    audit_rows = await db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.target_id == call_id,
            AuditEvent.action == "llm.settlement.reconcile",
        )
        .order_by(AuditEvent.created_at, AuditEvent.id)
        .limit(100)
    )
    audits = [
        CallAuditView(
            at=audit.created_at,
            actor_id=audit.actor_id,
            actor_name=safe_name(audit.actor_name),
            action="llm.settlement.reconcile",
            result=safe_code(audit.result) or "unknown",
            reconcile_action=cast(Any, audit.details.get("action"))
            if isinstance(audit.details, dict)
            and audit.details.get("action") in ("settle", "release")
            else None,
        )
        for audit in audit_rows
    ]
    return CallDetail(
        call=call_view(call, settlement, model, actor_membership, member_user),
        attempts=attempts,
        settlement=settlement_view(settlement) if settlement else None,
        audits=audits,
    )


def expected_fields(call: ModelCall, settlement: UsageSettlement | None) -> tuple[str, ...]:
    fields: set[str] = set()
    if settlement is not None and isinstance(settlement.price, dict):
        price = settlement.price
        metric = price.get("metric")
        if metric == "tokens":
            fields.update(
                field for field, rate in PRICE_FIELDS.items() if price.get(rate) is not None
            )
        elif metric in FIELDS:
            fields.update(FIELDS[metric])
    else:
        fields.update(
            {
                "chat": ("input_tokens", "output_tokens"),
                "embedding": ("input_tokens",),
                "rerank": ("search_units",),
                "image_generation": ("image_count",),
                "speech": ("input_characters",),
                "transcription": ("audio_duration_ms",),
            }.get(call.kind, ())
        )
    if isinstance(call.attempts, list):
        for attempt in call.attempts:
            if not isinstance(attempt, dict):
                continue
            for entry in attempt_evidence(
                attempt.get("usage_evidence"),
                attempt_id=safe_name(attempt.get("attempt_id"), length=128),
            ):
                if entry.field in buckets_fields() and entry.value is not None:
                    fields.add(entry.field)
    return tuple(field for names in FIELDS.values() for field in names if field in fields)


def buckets_fields() -> set[str]:
    return {field for names in FIELDS.values() for field in names}


def complete_attempt_value(raw: dict[str, Any], field: str) -> int | None:
    if (
        field in (*FIELDS["tokens"], *FIELDS["search_units"])
        and raw.get("upstream_terminal") is not True
    ):
        return None
    evidence = attempt_evidence(
        raw.get("usage_evidence"), attempt_id=safe_name(raw.get("attempt_id"), length=128)
    )
    complete = [
        entry.value
        for entry in evidence
        if entry.field == field and entry.complete and entry.value is not None
    ]
    return complete[0] if complete and len(set(complete)) == 1 else None


def accumulate_metrics(
    call: ModelCall, settlement: UsageSettlement | None, buckets: dict[str, list[int]]
) -> None:
    attempts = call.attempts if isinstance(call.attempts, list) else []
    for field in expected_fields(call, settlement):
        values: list[int] = []
        unknown = False
        observed = False
        for raw in attempts:
            if not isinstance(raw, dict):
                unknown = True
                continue
            if raw.get("sent") is False:
                if raw.get("certainly_unused") is not True:
                    unknown = True
                continue
            if raw.get("sent") is not True:
                unknown = True
                continue
            observed = True
            value = complete_attempt_value(raw, field)
            if value is None:
                unknown = True
            else:
                values.append(value)
        if not observed and not attempts:
            unknown = True
        bucket = buckets[field]
        if unknown:
            bucket[2] += 1
        else:
            bucket[0] += sum(values)
            bucket[1] += 1


async def usage_summary(db: AsyncSession, filters: CallFilters) -> UsageSummary:
    validate_filters(filters, summary=True)
    assert filters.from_time is not None and filters.to_time is not None
    now = datetime.now(UTC)
    counts = {name: 0 for name in RESULTS}
    settlements = {name: 0 for name in SETTLEMENTS}
    buckets = {field: [0, 0, 0] for names in FIELDS.values() for field in names}
    calls = attempts = 0
    amounts: dict[str, Decimal] = {}
    settled_points = Decimal(0)
    operation_groups: dict[str, list[Any]] = {}
    model_groups: dict[str, list[Any]] = {}
    query = where_calls(
        select(ModelCall, UsageSettlement, CatalogModel)
        .outerjoin(UsageSettlement, UsageSettlement.id == ModelCall.id)
        .outerjoin(CatalogModel, CatalogModel.id == ModelCall.model_id),
        filters,
    ).execution_options(yield_per=100)
    stream = await db.stream(query)
    try:
        async for call, settlement, model in stream:
            calls += 1
            call_attempts = len(call.attempts) if isinstance(call.attempts, list) else 0
            attempts += call_attempts
            counts[result_status(call)] += 1
            settlements[settlement.status if settlement else "not_applicable"] += 1
            point_value = Decimal(0)
            if settlement and settlement.status == "settled" and settlement.amount is not None:
                with localcontext() as ctx:
                    ctx.prec = 80
                    point_value = settlement.amount * settlement.ratio
                    settled_points += point_value
                    amounts[settlement.currency] = (
                        amounts.get(settlement.currency, Decimal(0)) + settlement.amount
                    )
            for key, groups, name in (
                (call.kind, operation_groups, None),
                (
                    str(call.model_id) if call.model_id else "unknown",
                    model_groups,
                    model.name if model else None,
                ),
            ):
                group = groups.setdefault(key, [name, 0, 0, Decimal(0)])
                group[1] += 1
                group[2] += call_attempts
                with localcontext() as ctx:
                    ctx.prec = 80
                    group[3] += point_value
            accumulate_metrics(call, settlement, buckets)
    finally:
        await stream.close()
    held = await current_held(db, filters, now)
    return UsageSummary(
        range=SummaryRange(
            from_time=filters.from_time,
            to_time=filters.to_time,
            timezone=filters.timezone_name,
            as_of=now,
        ),
        calls=calls,
        attempts=attempts,
        result_counts=counts,
        settlement_counts=settlements,
        settled_points=None if filters.source == "diagnostic" else decimal_text(settled_points),
        amounts_by_currency=[
            AmountBucket(currency=currency, amount=decimal_text(amount))
            for currency, amount in sorted(amounts.items())
        ],
        metrics=[
            MetricBucket(
                metric=cast(Any, metric),
                field=field,
                sum=str(buckets[field][0]),
                known_calls=buckets[field][1],
                unknown_calls=buckets[field][2],
            )
            for metric, fields in FIELDS.items()
            for field in fields
        ],
        by_operation=[
            DistributionBucket(
                key=key,
                name=None,
                calls=group[1],
                attempts=group[2],
                settled_points=None if filters.source == "diagnostic" else decimal_text(group[3]),
            )
            for key, group in sorted(operation_groups.items())
        ],
        by_model=[
            DistributionBucket(
                key=key,
                name=group[0],
                calls=group[1],
                attempts=group[2],
                settled_points=None if filters.source == "diagnostic" else decimal_text(group[3]),
            )
            for key, group in sorted(model_groups.items())
        ],
        current_held=held,
    )


async def current_held(db: AsyncSession, filters: CallFilters, as_of: datetime) -> CurrentHeld:
    if filters.source == "diagnostic":
        return CurrentHeld(points=None, as_of=as_of, scope=None, applicable=False)
    scope = HeldScope(
        member_id=filters.member_id,
        model_id=filters.model_id,
        operation=filters.operation,
        source=cast(Any, filters.source),
    )
    held_filters = CallFilters(
        tenant_id=filters.tenant_id,
        member_id=filters.member_id,
        model_id=filters.model_id,
        operation=filters.operation,
        source=filters.source,
        held=True,
    )
    query = where_calls(
        select(UsageSettlement.reserved_amount, UsageSettlement.ratio)
        .select_from(ModelCall)
        .join(UsageSettlement, UsageSettlement.id == ModelCall.id),
        held_filters,
    ).execution_options(yield_per=100)
    stream = await db.stream(query)
    total = Decimal(0)
    try:
        async for amount, ratio in stream:
            with localcontext() as ctx:
                ctx.prec = 80
                total += amount * ratio
    finally:
        await stream.close()
    return CurrentHeld(points=decimal_text(total), as_of=as_of, scope=scope, applicable=True)
