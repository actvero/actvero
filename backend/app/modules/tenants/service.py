from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent
from app.modules.experts.categories import seed_categories as seed_expert_categories
from app.modules.members.models import Membership
from app.modules.skills.categories import seed_categories
from app.modules.tenants.models import Installation, PlatformOperator, Tenant
from app.modules.users.models import LoginIdentity, User


async def finish_initial_setup(
    db: AsyncSession,
    identity: LoginIdentity,
    user: User,
    platform_edition: str = "community",
) -> None:
    """Called only after a validated OIDC login, in the same transaction as its session."""
    install = await db.scalar(
        select(Installation)
        .where(Installation.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        install is None
        or (
            install.tenant_id
            if platform_edition == "community"
            else install.platform_operator_user_id
        )
        or not install.subject
        or identity.issuer != install.issuer
        or identity.subject != install.subject
    ):
        return
    if platform_edition == "saas":
        db.add(PlatformOperator(user_id=user.id))
        install.platform_operator_user_id = user.id
        install.registration_marker = None
        return
    if not install.organization_name:
        return
    tenant = Tenant(name=install.organization_name)
    db.add(tenant)
    await db.flush()
    seed_categories(db, tenant.id)
    seed_expert_categories(db, tenant.id)
    db.add(Membership(tenant_id=tenant.id, user_id=user.id, role="administrator", source="setup"))
    install.tenant_id = tenant.id
    install.registration_marker = None
    db.add(
        AuditEvent(
            tenant_id=tenant.id,
            actor_id=user.id,
            actor_name=user.name,
            action="enterprise.created",
            target_id=tenant.id,
            target_name=tenant.name,
            details={},
        )
    )
