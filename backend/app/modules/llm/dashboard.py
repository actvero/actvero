"""One bounded snapshot for charts, rankings and logical-call flow, never billing writes."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from math import ceil
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.llm.call_queries import (
    FIELDS,
    RESULTS,
    SETTLEMENTS,
    CallFilters,
    accumulate_metrics,
    base_rows,
    current_held,
    result_status,
    safe_name,
    safe_uuid,
    validate_filters,
    where_calls,
)
from app.modules.llm.call_schemas import (
    AmountBucket,
    DistributionBucket,
    MetricBucket,
    SummaryRange,
    UsageSummary,
)
from app.modules.llm.dashboard_schemas import (
    DashboardGroup,
    FlowPath,
    PerformanceSummary,
    TimeBucket,
    UsageDashboard,
)
from app.modules.llm.models import ModelCall, ModelChannel, UsageSettlement
from app.modules.llm.points import decimal_text

MAX_CALLS = 50000
MAX_BUCKETS = 744


def boundaries(filters: CallFilters, granularity: str) -> tuple[str, list[datetime]]:
    validate_filters(filters, summary=True)
    assert filters.from_time is not None and filters.to_time is not None
    start, end = filters.from_time.astimezone(UTC), filters.to_time.astimezone(UTC)
    kind = (
        ("hour" if end - start <= timedelta(days=7) else "day")
        if granularity == "auto"
        else granularity
    )
    if kind not in ("hour", "day"):
        raise HTTPException(422, "时间粒度须为自动、小时或天")
    zone = ZoneInfo(filters.timezone_name)
    local = start.astimezone(zone)
    floor = local.replace(minute=0, second=0, microsecond=0)
    if kind == "day":
        floor = floor.replace(hour=0)
    edge = floor.astimezone(UTC)
    result = [start]
    while edge < end:
        if kind == "hour":
            edge += timedelta(hours=1)
        else:
            floor = (floor + timedelta(days=1)).replace(fold=0)
            edge = floor.astimezone(UTC)
        if start < edge < end:
            result.append(edge)
        if len(result) > MAX_BUCKETS:
            raise HTTPException(422, "时间桶超过744个，请选择按天或缩短范围")
    result.append(end)
    return kind, result


def metrics_view(buckets: dict[str, list[int]]) -> list[MetricBucket]:
    return [
        MetricBucket(
            metric=cast(Any, metric),
            field=name,
            sum=str(buckets[name][0]),
            known_calls=buckets[name][1],
            unknown_calls=buckets[name][2],
        )
        for metric, names in FIELDS.items()
        for name in names
    ]


@dataclass
class Group:
    name: str
    calls: int = 0
    successes: int = 0
    review: int = 0
    attempts: int = 0
    points: Decimal = Decimal(0)
    metrics: dict[str, list[int]] = field(
        default_factory=lambda: {name: [0, 0, 0] for names in FIELDS.values() for name in names}
    )

    def add(
        self,
        call: ModelCall,
        settlement: UsageSettlement | None,
        points: Decimal,
        quantities: dict[str, list[int]],
    ) -> None:
        self.calls += 1
        self.successes += result_status(call) == "success"
        self.review += settlement is not None and settlement.status == "review"
        self.attempts += len(call.attempts or [])
        self.points += points
        for name, values in quantities.items():
            for index in range(3):
                self.metrics[name][index] += values[index]

    def view(self, key: str, diagnostic: bool) -> DashboardGroup:
        return DashboardGroup(
            key=key,
            name=self.name,
            calls=self.calls,
            successes=self.successes,
            review=self.review,
            settled_points=None if diagnostic else decimal_text(self.points),
            metrics=metrics_view(self.metrics),
        )


def final_channel(call: ModelCall, names: dict[str, str]) -> str | None:
    # The root channel may be an initial choice. Only terminal evidence proves attribution.
    attempts = call.attempts if isinstance(call.attempts, list) else []
    if not attempts or not isinstance(attempts[-1], dict):
        return None
    last = attempts[-1]
    channel_id = last.get("channel_id")
    if (
        type(last.get("evidence_version")) is int
        and last.get("evidence_version") == 1
        and last.get("sent") is True
        and last.get("upstream_terminal") is True
        and isinstance(channel_id, str)
        and channel_id in names
        and last.get("status") in ("succeeded", "failed")
    ):
        return channel_id
    return None


async def usage_dashboard(
    db: AsyncSession,
    filters: CallFilters,
    *,
    granularity: str = "auto",
    top: int = 10,
    rank: str = "calls",
    selected_members: tuple[str, ...] = (),
) -> UsageDashboard:
    kind, edges = boundaries(filters, granularity)
    if top not in (5, 10, 20, 50) or rank not in (
        "calls",
        "points",
        "input_tokens",
        "output_tokens",
    ):
        raise HTTPException(422, "排行选项无效")
    if len(selected_members) > 5 or any(safe_uuid(key) is None for key in selected_members):
        raise HTTPException(422, "最多选择5个有效成员")
    diagnostic = filters.source == "diagnostic"
    if diagnostic and rank == "points":
        raise HTTPException(422, "诊断不参与积分排行")
    names = {
        str(key): name
        for key, name in (
            await db.execute(
                select(ModelChannel.id, ModelChannel.name).where(
                    ModelChannel.tenant_id == filters.tenant_id
                )
            )
        ).all()
    }
    zone = ZoneInfo(filters.timezone_name)
    labels = [edge.astimezone(zone).isoformat(timespec="minutes") for edge in edges[:-1]]
    total = Group("全部")
    timeline = [Group(label) for label in labels]
    members: dict[str, Group] = {}
    models: dict[str, Group] = {}
    operations: dict[str, Group] = {}
    selected = {key: [Group(label) for label in labels] for key in set(selected_members)}
    flows: dict[tuple[str | None, str, str | None, str | None], FlowPath] = {}
    counts = dict.fromkeys(RESULTS, 0)
    settlement_counts = dict.fromkeys(SETTLEMENTS, 0)
    amounts: dict[str, Decimal] = {}
    durations: list[int] = []
    as_of = datetime.now(UTC)
    query = (
        where_calls(base_rows(), filters)
        .order_by(ModelCall.created_at, ModelCall.id)
        .limit(MAX_CALLS + 1)
        .execution_options(yield_per=100)
    )
    stream = await db.stream(query)
    try:
        with localcontext() as context:
            context.prec = 80
            async for call, settlement, model, membership, user in stream:
                if total.calls >= MAX_CALLS:
                    raise HTTPException(
                        422, "范围内超过50000次调用，请缩短范围或增加筛选；未返回截断统计"
                    )
                point = Decimal(0)
                if settlement and settlement.status == "settled" and settlement.amount is not None:
                    point = settlement.amount * settlement.ratio
                    amounts[settlement.currency] = (
                        amounts.get(settlement.currency, Decimal(0)) + settlement.amount
                    )
                quantities = {name: [0, 0, 0] for names_ in FIELDS.values() for name in names_}
                accumulate_metrics(call, settlement, quantities)
                counts[result_status(call)] += 1
                settlement_counts[settlement.status if settlement else "not_applicable"] += 1
                member_key = (
                    str(settlement.member_id)
                    if settlement
                    else str(membership.id)
                    if membership
                    else "unknown"
                )
                member_name = safe_name(user.name) if user else None
                model_key = str(call.model_id) if call.model_id else "unknown"
                model_name = safe_name(model.name) if model else None
                index = bisect_right(edges, call.created_at.astimezone(UTC)) - 1
                for group in (
                    total,
                    timeline[index],
                    members.setdefault(member_key, Group(member_name or "未确定成员")),
                    models.setdefault(model_key, Group(model_name or "未确定模型")),
                    operations.setdefault(call.kind, Group(call.kind)),
                ):
                    group.add(call, settlement, point, quantities)
                if member_key in selected:
                    selected[member_key][index].add(call, settlement, point, quantities)
                if (
                    type(call.duration_ms) is int
                    and call.duration_ms >= 0
                    and result_status(call) != "unknown"
                ):
                    durations.append(call.duration_ms)
                channel_key = final_channel(call, names)
                path_key = (
                    None if member_key == "unknown" else member_key,
                    call.source,
                    None if model_key == "unknown" else model_key,
                    channel_key,
                )
                if path_key not in flows:
                    flows[path_key] = FlowPath(
                        member_id=path_key[0],
                        member_name=member_name or "未确定成员",
                        source=call.source,
                        model_id=path_key[2],
                        model_name=model_name or "未确定模型",
                        channel_id=channel_key,
                        channel_name=names.get(channel_key or "", "未确定渠道"),
                        calls=0,
                    )
                flows[path_key].calls += 1
    finally:
        await stream.close()

    def order(item: tuple[str, Group]) -> tuple[Decimal, str]:
        key, group = item
        value = (
            Decimal(group.calls)
            if rank == "calls"
            else group.points
            if rank == "points"
            else Decimal(group.metrics[rank][0])
        )
        return value.copy_negate(), key

    ranked = sorted(members.items(), key=order)
    other = Group("其他成员")
    with localcontext() as context:
        context.prec = 80
        for _, group in ranked[top:]:
            other.calls += group.calls
            other.points += group.points
            other.review += group.review
            other.successes += group.successes
            for name, values in group.metrics.items():
                for i in range(3):
                    other.metrics[name][i] += values[i]
    paths = sorted(
        flows.values(),
        key=lambda path: (
            -path.calls,
            str(path.member_id),
            path.source,
            str(path.model_id),
            str(path.channel_id),
        ),
    )
    durations.sort()
    assert filters.from_time is not None and filters.to_time is not None
    range_ = SummaryRange(
        from_time=filters.from_time,
        to_time=filters.to_time,
        timezone=filters.timezone_name,
        as_of=as_of,
    )

    def distribution(groups: dict[str, Group]) -> list[DistributionBucket]:
        return [
            DistributionBucket(
                key=key,
                name=group.name,
                calls=group.calls,
                attempts=group.attempts,
                settled_points=None if diagnostic else decimal_text(group.points),
            )
            for key, group in sorted(groups.items())
        ]

    def times(groups: list[Group]) -> list[TimeBucket]:
        return [
            TimeBucket(
                **group.view(str(i), diagnostic).model_dump(),
                from_time=edges[i],
                to_time=edges[i + 1],
            )
            for i, group in enumerate(groups)
        ]

    return UsageDashboard(
        summary=UsageSummary(
            range=range_,
            calls=total.calls,
            attempts=total.attempts,
            result_counts=counts,
            settlement_counts=settlement_counts,
            settled_points=None if diagnostic else decimal_text(total.points),
            metrics=metrics_view(total.metrics),
            amounts_by_currency=[
                AmountBucket(currency=key, amount=decimal_text(value))
                for key, value in sorted(amounts.items())
            ],
            by_operation=distribution(operations),
            by_model=distribution(models),
            current_held=await current_held(db, filters, as_of),
        ),
        granularity=cast(Literal["hour", "day"], kind),
        timeline=times(timeline),
        members=[group.view(key, diagnostic) for key, group in ranked[:top]],
        models=[
            group.view(key, diagnostic) for key, group in sorted(models.items(), key=order)[:top]
        ],
        member_names={key: members[key].name for key in selected if key in members},
        member_timelines={key: times(groups) for key, groups in selected.items() if key in members},
        member_count=len(members),
        other_members=other.view("other", diagnostic),
        flow=paths[:top],
        other_flow_calls=sum(path.calls for path in paths[top:]),
        performance=PerformanceSummary(
            average_ms=sum(durations) / len(durations) if durations else None,
            p95_ms=durations[ceil(0.95 * len(durations)) - 1] if durations else None,
            samples=len(durations),
            calls=total.calls,
            rpm=total.calls / ((filters.to_time - filters.from_time).total_seconds() / 60),
        ),
    )
