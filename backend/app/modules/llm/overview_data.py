"""Read-only projections for the organization home page."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.modules.experts.models import ExpertRecord, ExpertRelease
from app.modules.experts.schemas import ExpertContent
from app.modules.experts.service import check as check_expert
from app.modules.knowledge.models import KnowledgeBase, KnowledgeDocument, KnowledgeGeneration
from app.modules.llm.call_queries import safe_name
from app.modules.llm.dashboard_schemas import OverviewAttention, OverviewKnowledge, ResourceCount
from app.modules.llm.models import ModelCall
from app.modules.mcp.models import McpActivity
from app.modules.members.models import Membership
from app.modules.workbenches.models import Workbench, WorkbenchVersion

IMPORTANT_ACTIONS = (
    "experts.publish",
    "experts.withdraw",
    "experts.scope",
    "skills.publish",
    "skills.withdraw",
    "skills.update",
    "skills.default",
    "workbench.publish",
    "workbench.withdraw",
    "workbench.scope",
    "workbench.runtime_config",
    "knowledge.create",
    "knowledge.update",
    "knowledge.archive",
    "knowledge.defaults",
    "llm.channel.create",
    "llm.channel.update",
    "llm.channel.archive",
    "llm.channel.restore",
    "llm.model.create",
    "llm.model.update",
    "llm.model.archive",
    "llm.model.restore",
    "llm.points.configure",
    "quota.policy.create",
    "quota.policy.update",
    "quota.member.assign",
    "quota.policy.archive",
    "quota.policy.restore",
    "mcp.create",
    "mcp.update",
    "mcp.delete",
    "mcp.policy",
    "mcp.import",
    "member.role",
    "member.departments",
    "member.pause",
    "member.remove",
)


async def expert_status(
    db: AsyncSession, tenant_id: UUID
) -> tuple[ResourceCount, int, OverviewAttention | None]:
    current = and_(
        ExpertRelease.expert_id == ExpertRecord.id,
        ExpertRelease.id == ExpertRecord.current_release_id,
    )
    total, published, changed = (
        await db.execute(
            select(
                func.count(ExpertRecord.id),
                func.count(ExpertRelease.id),
                func.count().filter(
                    ExpertRelease.id.is_not(None), ExpertRecord.draft != ExpertRelease.content
                ),
            )
            .select_from(ExpertRecord)
            .outerjoin(ExpertRelease, current)
            .where(ExpertRecord.tenant_id == tenant_id)
        )
    ).one()
    rows = (
        (
            await db.execute(
                select(ExpertRecord, ExpertRelease.content, ExpertRelease.dependency_refs)
                .options(
                    load_only(
                        ExpertRecord.id,
                        ExpertRecord.name,
                        ExpertRecord.tenant_id,
                        ExpertRecord.audience,
                        ExpertRecord.member_ids,
                        ExpertRecord.department_grants,
                    )
                )
                .join(ExpertRelease, current)
                .where(
                    ExpertRecord.tenant_id == tenant_id,
                    or_(
                        ExpertRelease.content["skills"] != [],
                        ExpertRelease.content["connectors"] != [],
                    ),
                )
                .order_by(ExpertRecord.name, ExpertRecord.id)
            )
        )
        .tuples()
        .all()
    )
    issues: list[tuple[UUID, str]] = []
    for expert, content, refs in rows:
        state = await check_expert(
            db, expert, ExpertContent.model_validate(content), refs.get("connectors")
        )
        if any(
            d.required and (d.status in {"unavailable", "version_conflict"} or d.missing_members)
            for d in state.dependencies
        ):
            issues.append((expert.id, expert.name))
    attention = (
        OverviewAttention(
            count=len(issues),
            resource_id=issues[0][0],
            name=safe_name(issues[0][1]) or "已发布专家",
        )
        if issues
        else None
    )
    return ResourceCount(total=total, enabled=published), changed, attention


async def workbench_status(db: AsyncSession, tenant_id: UUID) -> tuple[ResourceCount, int]:
    versions = select(WorkbenchVersion.id).where(WorkbenchVersion.workbench_id == Workbench.id)
    total, published, drafts = (
        await db.execute(
            select(
                func.count(Workbench.id),
                func.count().filter(
                    versions.where(WorkbenchVersion.status == "published").exists()
                ),
                func.count().filter(versions.where(WorkbenchVersion.status == "draft").exists()),
            ).where(Workbench.tenant_id == tenant_id)
        )
    ).one()
    return ResourceCount(total=total, enabled=published), drafts


async def knowledge_status(
    db: AsyncSession, tenant_id: UUID
) -> tuple[OverviewKnowledge, OverviewAttention | None]:
    base_filters = (KnowledgeBase.tenant_id == tenant_id, KnowledgeBase.archived.is_(False))
    documents = (
        select(
            KnowledgeBase.id.label("base_id"),
            KnowledgeBase.name,
            KnowledgeGeneration.status,
            KnowledgeGeneration.error,
        )
        .join(KnowledgeDocument, KnowledgeDocument.base_id == KnowledgeBase.id)
        .outerjoin(
            KnowledgeGeneration,
            and_(
                KnowledgeGeneration.id == KnowledgeDocument.latest_generation_id,
                KnowledgeGeneration.document_id == KnowledgeDocument.id,
            ),
        )
        .where(*base_filters, KnowledgeDocument.deleted_at.is_(None))
        .subquery()
    )
    needs_attention = or_(
        documents.c.status.in_(("failed", "uncertain")),
        and_(
            documents.c.status == "waiting",
            documents.c.error.startswith("等待可用的 MinerU 凭据"),
        ),
    )
    total = await db.scalar(select(func.count(KnowledgeBase.id)).where(*base_filters)) or 0
    count, processing, failed = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(
                    documents.c.status.in_(
                        ("queued", "parsing", "chunking", "indexing", "waiting")
                    ),
                    ~needs_attention,
                ),
                func.count().filter(needs_attention),
            ).select_from(documents)
        )
    ).one()
    first = (
        (
            await db.execute(
                select(documents.c.base_id, documents.c.name)
                .where(needs_attention)
                .order_by(documents.c.name, documents.c.base_id)
                .limit(1)
            )
        ).first()
        if failed
        else None
    )
    return OverviewKnowledge(total=total, documents=count, processing=processing), (
        OverviewAttention(
            count=failed, resource_id=first.base_id, name=safe_name(first.name) or "知识库"
        )
        if first
        else None
    )


async def business_activity(
    db: AsyncSession, tenant_id: UUID, start: datetime, end: datetime
) -> tuple[int, int]:
    tool_calls = select(McpActivity.actor_id).where(
        McpActivity.tenant_id == tenant_id,
        McpActivity.created_at >= start,
        McpActivity.created_at < end,
        McpActivity.category == "call",
        McpActivity.operation.in_(("tools", "tools/call")),
        McpActivity.source.in_(("desktop", "access_key")),
    )
    model_users = select(ModelCall.actor_id).where(
        ModelCall.tenant_id == tenant_id,
        ModelCall.created_at >= start,
        ModelCall.created_at < end,
        ModelCall.source.in_(("desktop", "access_key")),
    )
    users = model_users.union(tool_calls).subquery()
    active = (
        await db.scalar(
            select(func.count(func.distinct(users.c.actor_id))).join(
                Membership,
                and_(
                    Membership.user_id == users.c.actor_id,
                    Membership.tenant_id == tenant_id,
                    Membership.status == "active",
                ),
            )
        )
        or 0
    )
    tool_count = await db.scalar(select(func.count()).select_from(tool_calls.subquery())) or 0
    return active, tool_count
