"""Read-only dashboard projections; exact quantities stay decimal strings."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.modules.llm.call_schemas import MetricBucket, UsageSummary


class DashboardGroup(BaseModel):
    key: str
    name: str
    calls: int = 0
    successes: int = 0
    review: int = 0
    settled_points: str | None = None
    metrics: list[MetricBucket] = Field(default_factory=list)


class TimeBucket(DashboardGroup):
    from_time: datetime
    to_time: datetime


class FlowPath(BaseModel):
    member_id: UUID | None
    member_name: str
    source: str
    model_id: UUID | None
    model_name: str
    channel_id: UUID | None
    channel_name: str
    calls: int


class PerformanceSummary(BaseModel):
    average_ms: float | None
    p95_ms: int | None
    samples: int
    calls: int
    rpm: float


class UsageDashboard(BaseModel):
    summary: UsageSummary
    granularity: Literal["hour", "day"]
    timeline: list[TimeBucket]
    members: list[DashboardGroup]
    models: list[DashboardGroup]
    member_names: dict[str, str] = Field(default_factory=dict)
    member_timelines: dict[str, list[TimeBucket]]
    member_count: int
    other_members: DashboardGroup
    flow: list[FlowPath]
    other_flow_calls: int
    performance: PerformanceSummary


class ResourceCount(BaseModel):
    total: int
    enabled: int


class OverviewActivity(BaseModel):
    at: datetime
    actor: str
    action: str
    target: str


class OrganizationOverview(BaseModel):
    as_of: datetime
    models: ResourceCount
    channels: ResourceCount
    skills: ResourceCount
    mcp: ResourceCount
    members: ResourceCount
    review_calls: int
    mcp_calls: int
    skill_distributions: int
    mcp_checked: int
    mcp_failed: int
    mcp_unchecked: int
    activities: list[OverviewActivity]


class PersonalOverview(BaseModel):
    from_time: datetime
    to_time: datetime
    calls: int
    settled_points: str
    review_calls: int
