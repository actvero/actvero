from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import and_, select

from app.modules.auth.service import DB, authenticate, provider
from app.modules.members.models import Membership
from app.modules.members.service import membership_state
from app.modules.tenants.models import Installation, PlatformOperator, Tenant
from app.modules.users.models import LoginIdentity, User


@dataclass
class PlatformActor:
    user: User
    authenticated_at: datetime | None = None


async def community_instance_administrator(
    db: DB, user_id: UUID, authenticated_at: datetime | None
) -> bool:
    """Only the setup identity with a current administrator membership owns the instance.

    The persisted issuer/subject also covers existing installations. Neither an
    email match nor a later organization administrator grants installation access.
    """
    row = (
        await db.execute(
            select(Membership, Tenant)
            .join(Tenant, Tenant.id == Membership.tenant_id)
            .join(Installation, Installation.tenant_id == Tenant.id)
            .join(
                LoginIdentity,
                and_(
                    LoginIdentity.issuer == Installation.issuer,
                    LoginIdentity.subject == Installation.subject,
                ),
            )
            .where(
                Installation.id == 1,
                LoginIdentity.user_id == user_id,
                Membership.user_id == user_id,
                Membership.role == "administrator",
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    return bool(row and membership_state(row[1], row[0], authenticated_at) is None)


async def system_administrator(
    db: DB, user_id: UUID, edition: str, authorized_at: datetime | None
) -> bool:
    if edition == "community":
        return await community_instance_administrator(db, user_id, authorized_at)
    return bool(
        await db.scalar(
            select(PlatformOperator.user_id).where(
                PlatformOperator.user_id == user_id, PlatformOperator.status == "active"
            )
        )
    )


async def require_system_grant(request: Request, db: DB, actor: PlatformActor) -> None:
    """Recheck the grant without authenticating/committing an installation mutation lock."""
    edition = provider(request).settings.platform_edition
    if not await system_administrator(db, actor.user.id, edition, actor.authenticated_at):
        raise HTTPException(
            403, "此操作仅限实例管理员" if edition == "community" else "此页面仅限平台运营人员"
        )


async def system_access(request: Request, db: DB) -> PlatformActor:
    """Installation settings are available in both editions, with separate grants."""
    session, _, user = await authenticate(request, db)
    actor = PlatformActor(user, session.authenticated_at)
    await require_system_grant(request, db, actor)
    return actor


async def platform_access(request: Request, db: DB) -> PlatformActor:
    if provider(request).settings.platform_edition != "saas":
        raise HTTPException(404, "社区版不提供平台组织管理")
    _, _, user = await authenticate(request, db)
    operator = await db.scalar(
        select(PlatformOperator).where(
            PlatformOperator.user_id == user.id, PlatformOperator.status == "active"
        )
    )
    if operator is None:
        raise HTTPException(403, "此页面仅限平台运营人员")
    return PlatformActor(user)
