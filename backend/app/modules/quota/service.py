from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members.models import Membership
from app.modules.quota.models import QuotaAssignment, QuotaPolicy


async def matching_policies(
    db: AsyncSession, tenant_id: UUID, member_id: UUID
) -> list[QuotaPolicy]:
    """Resolve one explicit assignment, otherwise the organization default."""
    active_member = await db.scalar(
        select(Membership.id).where(
            Membership.tenant_id == tenant_id,
            Membership.id == member_id,
            Membership.status == "active",
        )
    )
    if active_member is None:
        return []
    selected = await configured_policy(db, tenant_id, member_id)
    return [selected] if selected else []


async def configured_policy(
    db: AsyncSession, tenant_id: UUID, member_id: UUID
) -> QuotaPolicy | None:
    """Read policy metadata; runtime callers must also require active membership."""
    assignment = await db.scalar(
        select(QuotaAssignment).where(
            QuotaAssignment.tenant_id == tenant_id, QuotaAssignment.member_id == member_id
        )
    )
    policy: QuotaPolicy | None = await db.scalar(
        select(QuotaPolicy).where(
            QuotaPolicy.tenant_id == tenant_id,
            QuotaPolicy.archived.is_(False),
            QuotaPolicy.id == assignment.policy_id
            if assignment and assignment.policy_id
            else QuotaPolicy.is_default.is_(True),
        )
    )
    return policy
