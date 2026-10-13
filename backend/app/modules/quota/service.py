from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members.models import Membership
from app.modules.quota.models import QuotaPolicy


async def matching_policies(
    db: AsyncSession, tenant_id: UUID, member_id: UUID
) -> list[QuotaPolicy]:
    """Select whole policies, never merge windows or grant model access."""
    active_member = (
        select(Membership.id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.id == member_id,
            Membership.status == "active",
        )
        .exists()
    )
    return list(
        await db.scalars(
            select(QuotaPolicy)
            .where(
                QuotaPolicy.tenant_id == tenant_id,
                QuotaPolicy.archived.is_(False),
                (QuotaPolicy.priority == 0) | QuotaPolicy.member_ids.contains([str(member_id)]),
                active_member,
            )
            .order_by(QuotaPolicy.priority.desc())
        )
    )
