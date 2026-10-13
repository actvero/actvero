"""Read-only, organization-scoped dashboards and safe personal overview."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from sqlalchemy import case, func, select

from app.modules.account.service import own_access
from app.modules.audit.models import AuditEvent
from app.modules.auth.service import DB
from app.modules.llm.call_queries import FORMAL, CallFilters, safe_name
from app.modules.llm.dashboard import usage_dashboard
from app.modules.llm.dashboard_schemas import (
    OrganizationOverview,
    OverviewActivity,
    PersonalOverview,
    ResourceCount,
    UsageDashboard,
)
from app.modules.llm.models import CatalogModel, ModelCall, ModelChannel, UsageSettlement
from app.modules.llm.points import decimal_text
from app.modules.llm.router import administrator
from app.modules.mcp.credentials import SHARED
from app.modules.mcp.models import McpActivity, McpHealth, McpService
from app.modules.members.models import Membership
from app.modules.skills.models import Skill, SkillDistribution, SkillVersion

router = APIRouter(prefix="/api/v1", tags=["dashboard"])


@router.get("/llm/dashboard", response_model=UsageDashboard)
async def dashboard(
    request: Request,
    db: DB,
    from_time: Annotated[datetime, Query(alias="from")],
    to_time: Annotated[datetime, Query(alias="to")],
    timezone: Annotated[str, Query(max_length=100)] = "UTC",
    member_id: UUID | None = None,
    model_id: UUID | None = None,
    operation: str | None = None,
    source: str = "member",
    result_status: str | None = None,
    settlement_status: str | None = None,
    channel_id: UUID | None = None,
    unknown_channel: bool = False,
    granularity: str = "auto",
    top: int = 10,
    rank: str = "calls",
    selected_members: Annotated[str, Query(max_length=200)] = "",
) -> UsageDashboard:
    actor = await administrator(request, db)
    return await usage_dashboard(
        db,
        CallFilters(
            tenant_id=actor.tenant.id,
            from_time=from_time,
            to_time=to_time,
            timezone_name=timezone,
            member_id=member_id,
            model_id=model_id,
            operation=operation,
            source=source,
            channel_id=channel_id,
            unknown_channel=unknown_channel,
            result_status=result_status,
            settlement_status=settlement_status,
        ),
        granularity=granularity,
        top=top,
        rank=rank,
        selected_members=tuple(selected_members.split(",")) if selected_members else (),
    )


@router.get("/overview", response_model=OrganizationOverview)
async def overview(request: Request, db: DB) -> OrganizationOverview:
    actor = await administrator(request, db)
    tenant_id = actor.tenant.id
    as_of = datetime.now(UTC)
    start = as_of - timedelta(hours=24)

    async def count(model: type, *conditions: Any) -> int:
        return (await db.scalar(select(func.count()).select_from(model).where(*conditions))) or 0

    models = (
        await db.scalars(
            select(CatalogModel).where(
                CatalogModel.tenant_id == tenant_id, CatalogModel.archived.is_(False)
            )
        )
    ).all()
    open_models = sum(
        bool((model.configuration or {}).get("access", {}).get("enabled")) for model in models
    )
    channels = ResourceCount(
        total=await count(
            ModelChannel, ModelChannel.tenant_id == tenant_id, ModelChannel.archived.is_(False)
        ),
        enabled=await count(
            ModelChannel,
            ModelChannel.tenant_id == tenant_id,
            ModelChannel.archived.is_(False),
            ModelChannel.manual_enabled.is_(True),
        ),
    )
    skills = ResourceCount(
        total=await count(Skill, Skill.tenant_id == tenant_id),
        enabled=int(
            await db.scalar(
                select(func.count(SkillVersion.id))
                .join(Skill, Skill.id == SkillVersion.skill_id)
                .where(Skill.tenant_id == tenant_id, SkillVersion.status == "published")
            )
            or 0
        ),
    )
    services = (await db.scalars(select(McpService).where(McpService.tenant_id == tenant_id))).all()
    health_rows = (
        await db.scalars(
            select(McpHealth)
            .join(McpService, McpService.id == McpHealth.service_id)
            .where(
                McpService.tenant_id == tenant_id, McpHealth.owner_id.in_((actor.member.id, SHARED))
            )
        )
    ).all()
    health_by_owner = {(row.service_id, row.owner_id): row for row in health_rows}
    checked = failed = unchecked = 0
    for service in services:
        if (
            not service.enabled
            or not (service.connection_options or {}).get("health_enabled")
            or service.transport == "builtin"
        ):
            continue
        owner = actor.member.id if service.auth_mode in ("personal", "oauth") else SHARED
        health = health_by_owner.get((service.id, owner))
        if (
            health is None
            or health.checked_at is None
            or health.next_check_at < as_of - timedelta(minutes=5)
        ):
            unchecked += 1
        elif health.error:
            failed += 1
        else:
            checked += 1
    activity = (
        await db.scalars(
            select(AuditEvent)
            .where(AuditEvent.tenant_id == tenant_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(5)
        )
    ).all()
    return OrganizationOverview(
        as_of=as_of,
        models=ResourceCount(total=len(models), enabled=open_models),
        channels=channels,
        skills=skills,
        mcp=ResourceCount(
            total=len(services), enabled=sum(service.enabled for service in services)
        ),
        members=ResourceCount(
            total=await count(
                Membership, Membership.tenant_id == tenant_id, Membership.status != "removed"
            ),
            enabled=await count(
                Membership, Membership.tenant_id == tenant_id, Membership.status == "active"
            ),
        ),
        review_calls=await count(
            UsageSettlement,
            UsageSettlement.tenant_id == tenant_id,
            UsageSettlement.status == "review",
        ),
        mcp_calls=await count(
            McpActivity,
            McpActivity.tenant_id == tenant_id,
            McpActivity.category == "call",
            McpActivity.created_at >= start,
            McpActivity.created_at < as_of,
        ),
        skill_distributions=await count(
            SkillDistribution,
            SkillDistribution.tenant_id == tenant_id,
            SkillDistribution.created_at >= start,
            SkillDistribution.created_at < as_of,
        ),
        mcp_checked=checked,
        mcp_failed=failed,
        mcp_unchecked=unchecked,
        activities=[
            OverviewActivity(
                at=row.created_at,
                actor=safe_name(row.actor_name) or "未知操作人",
                action=row.action,
                target=safe_name(row.target_name) or "—",
            )
            for row in activity
        ],
    )


@router.get("/account/overview", response_model=PersonalOverview)
async def personal_overview(request: Request, db: DB) -> PersonalOverview:
    actor = await own_access(request, db)
    end = datetime.now(UTC)
    start = end - timedelta(hours=24)
    calls, points = (
        await db.execute(
            select(
                func.count(ModelCall.id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                (UsageSettlement.status == "settled")
                                & UsageSettlement.amount.is_not(None),
                                UsageSettlement.amount * UsageSettlement.ratio,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
            )
            .select_from(ModelCall)
            .outerjoin(
                UsageSettlement,
                (UsageSettlement.id == ModelCall.id)
                & (UsageSettlement.tenant_id == actor.tenant.id),
            )
            .where(
                ModelCall.tenant_id == actor.tenant.id,
                ModelCall.actor_id == actor.user.id,
                ModelCall.source.in_(FORMAL),
                ModelCall.created_at >= start,
                ModelCall.created_at < end,
            )
        )
    ).one()
    review = await db.scalar(
        select(func.count())
        .select_from(UsageSettlement)
        .where(
            UsageSettlement.tenant_id == actor.tenant.id,
            UsageSettlement.member_id == actor.member.id,
            UsageSettlement.status == "review",
        )
    )
    return PersonalOverview(
        from_time=start,
        to_time=end,
        calls=calls,
        settled_points=decimal_text(points),
        review_calls=review or 0,
    )
