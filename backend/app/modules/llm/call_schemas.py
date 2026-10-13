"""Safe administrator projections for logical calls and bounded usage statistics."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

ResultStatus = Literal["success", "failed", "interrupted", "cancelled", "unknown"]
SettlementStatus = Literal["reserved", "review", "settled", "released", "not_applicable"]
SourceFilter = Literal["member", "desktop", "access_key", "diagnostic", "all"]
SummarySource = Literal["member", "desktop", "access_key", "diagnostic"]


class LogicalCallView(BaseModel):
    id: UUID
    created_at: datetime
    model_id: UUID | None
    model_name: str | None
    member_id: UUID | None
    member_name: str | None
    operation: str
    source: str
    result_status: ResultStatus
    settlement_status: SettlementStatus
    attempt_count: int
    duration_ms: int | None
    terminal_reason: str | None
    points: str | None
    # Historical admission reservation, not this call's current held balance.
    reserved_points: str | None


class CallPage(BaseModel):
    items: list[LogicalCallView]
    total: int
    page: int
    page_size: int = 20


class UsageEvidenceView(BaseModel):
    field: str
    value: int | None
    metric: str
    source: str
    complete: bool
    phase: str
    attempt_id: str | None
    evidence_version: int | None


class CallAttemptView(BaseModel):
    number: int | None
    attempt_id: str | None
    evidence_version: int | None
    operation: str | None
    binding_id: UUID | None
    channel_id: UUID | None
    channel_name: str | None
    upstream_id: str | None
    config_version: int | None
    channel_version: int | None
    started_at: datetime | None
    status: str | None
    sent: bool | None
    output_started: bool | None
    first_output_ms: int | None
    upstream_terminal: bool | None
    client_terminal: bool | None
    upstream_status: int | None
    retry_after_seconds: int | None
    retry_reason: str | None
    error_code: str | None
    error_scope: str | None
    retryable_hint: bool | None
    uncertain: bool | None
    certainly_unused: bool | None
    duration_ms: int | None
    usage_evidence: list[UsageEvidenceView]
    budget_price: PriceSnapshotView | None = None
    procurement_price: PriceSnapshotView | None = None
    budget_estimate: str | None = None
    procurement_estimate: str | None = None


class PriceSnapshotView(BaseModel):
    metric: str
    currency: str
    unit: int
    input: str | None
    output: str | None
    cache_read: str | None
    cache_write_5m: str | None
    cache_write_1h: str | None


class CallSettlementView(BaseModel):
    id: UUID
    status: SettlementStatus
    version: int
    currency: str
    ratio: str
    reserved_amount: str
    amount: str | None
    reserved_points: str
    points: str | None
    created_at: datetime
    settled_at: datetime | None
    budget_price: PriceSnapshotView | None
    conversion_id: UUID | None
    policy: PolicySnapshotView | None
    windows: list[WindowSnapshotView]


class PolicySnapshotView(BaseModel):
    id: UUID | None
    name: str | None
    version: int | None


class WindowSnapshotView(BaseModel):
    kind: str | None
    points: str | None
    hours: int | None
    timezone: str | None
    week_start: int | None
    used: str | None
    reserved: str | None
    remaining: str | None
    started_at: datetime | None
    resets_at: datetime | None


class CallAuditView(BaseModel):
    at: datetime
    actor_id: UUID
    actor_name: str | None
    action: str
    result: str
    reconcile_action: Literal["settle", "release"] | None


class CallDetail(BaseModel):
    call: LogicalCallView
    attempts: list[CallAttemptView]
    settlement: CallSettlementView | None
    audits: list[CallAuditView]


class SummaryRange(BaseModel):
    from_time: datetime
    to_time: datetime
    timezone: str
    as_of: datetime


class AmountBucket(BaseModel):
    currency: str
    amount: str


class MetricBucket(BaseModel):
    metric: Literal["tokens", "characters", "search_units", "images", "seconds"]
    field: str
    sum: str
    known_calls: int
    unknown_calls: int


class DistributionBucket(BaseModel):
    key: str
    name: str | None
    calls: int
    attempts: int
    settled_points: str | None


class HeldScope(BaseModel):
    member_id: UUID | None
    model_id: UUID | None
    operation: str | None
    source: Literal["member", "desktop", "access_key"]


class CurrentHeld(BaseModel):
    points: str | None
    as_of: datetime
    scope: HeldScope | None
    applicable: bool


class UsageSummary(BaseModel):
    range: SummaryRange
    calls: int
    attempts: int
    result_counts: dict[str, int]
    settlement_counts: dict[str, int]
    settled_points: str | None
    amounts_by_currency: list[AmountBucket]
    metrics: list[MetricBucket]
    by_operation: list[DistributionBucket]
    by_model: list[DistributionBucket]
    current_held: CurrentHeld
