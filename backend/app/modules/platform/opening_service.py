from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent
from app.modules.experts.categories import seed_categories as seed_expert_categories
from app.modules.members.models import Membership
from app.modules.skills.categories import seed_categories
from app.modules.tenants.models import Installation, Tenant
from app.modules.users.models import User


async def create_organization(
    db: AsyncSession, name: str, admin: User, actor: User, details: dict[str, str] | None = None
) -> Tenant:
    # Serialize organization names and initialization, including concurrent approvals.
    await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    if await db.scalar(select(Tenant.id).where(func.lower(Tenant.name) == name.casefold())):
        raise HTTPException(409, "组织名称已存在，请修改名称")
    tenant = Tenant(name=name)
    db.add(tenant)
    await db.flush()
    seed_categories(db, tenant.id)
    seed_expert_categories(db, tenant.id)
    db.add(
        Membership(tenant_id=tenant.id, user_id=admin.id, role="administrator", source="opening")
    )
    audit(db, actor, tenant, "organization.created", details)
    return tenant


def audit(
    db: AsyncSession,
    actor: User,
    tenant: Tenant,
    action: str,
    details: dict[str, str] | None = None,
) -> None:
    db.add(
        AuditEvent(
            tenant_id=tenant.id,
            actor_id=actor.id,
            actor_name=actor.name,
            action=action,
            target_id=tenant.id,
            target_name=tenant.name,
            details=details or {},
        )
    )


async def operator_member(db: AsyncSession, tenant_id: UUID, user_id: UUID) -> Membership:
    # A durable actor reference for per-person diagnostics; no other user's credentials.
    row = await db.scalar(
        select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
    )
    if row is None:
        row = Membership(
            tenant_id=tenant_id, user_id=user_id, role="administrator", source="platform"
        )
        db.add(row)
        await db.flush()
    return row
