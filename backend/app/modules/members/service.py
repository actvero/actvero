from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import WebSession
from app.modules.auth.service import authenticate, provider
from app.modules.members.models import Membership
from app.modules.members.schemas import MemberView
from app.modules.tenants.models import Installation, PlatformOperator, Tenant
from app.modules.users.models import LoginIdentity, User


@dataclass
class BusinessActor:
    user: User
    member: Membership
    tenant: Tenant


@dataclass
class Access(BusinessActor):
    session: WebSession


async def access(
    request: Request, db: AsyncSession, tenant_id: UUID, admin: bool = True, write: bool = False
) -> Access:
    session, _, user = await authenticate(request, db)
    installation = await db.get(Installation, 1)
    settings = provider(request).settings
    if settings.platform_edition == "community" and (
        not installation or installation.tenant_id != tenant_id
    ):
        raise HTTPException(403, "你没有此组织的访问权限")
    # All membership writes lock the tenant before reading current authorization.
    # This serializes concurrent removals, role changes and invitation acceptance.
    query = select(Tenant).where(Tenant.id == tenant_id)
    if write:
        query = query.with_for_update()
    tenant = await db.scalar(query.execution_options(populate_existing=True))
    member = await db.scalar(
        select(Membership)
        .where(Membership.tenant_id == tenant_id, Membership.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    operator = (
        await db.scalar(
            select(PlatformOperator).where(
                PlatformOperator.user_id == user.id, PlatformOperator.status == "active"
            )
        )
        if settings.platform_edition == "saas"
        else None
    )
    if operator and tenant and member:
        # Keep ordinary membership unchanged; this actor is elevated only for this Web request.
        scoped_member = Membership(
            id=member.id,
            tenant_id=tenant.id,
            user_id=user.id,
            role="administrator",
            status="active",
            source="platform",
            version=member.version,
        )
        return Access(user, scoped_member, tenant, session)
    reason = membership_state(tenant, member, session.authenticated_at)
    if reason:
        raise HTTPException(
            401 if reason == "reauthentication_required" else 403,
            "企业访问曾被暂停，请重新登录"
            if reason == "reauthentication_required"
            else "你没有此企业的有效访问权限",
        )
    assert tenant is not None and member is not None
    if admin and member.role != "administrator":
        raise HTTPException(403, "此操作仅限本企业管理员")
    return Access(user, member, tenant, session)


def member_view(member: Membership, user: User, actor: User) -> MemberView:
    return MemberView(
        id=member.id,
        name=user.name,
        email=user.email,
        role=member.role,
        status=member.status,
        source=member.source,
        version=member.version,
        joined_at=member.joined_at,
        is_self=user.id == actor.id,
    )


def record(
    db: AsyncSession,
    actor: BusinessActor,
    action: str,
    target_id: UUID,
    target_name: str,
    details: dict[str, str] | None = None,
    result: str = "success",
) -> None:
    db.add(
        AuditEvent(
            tenant_id=actor.tenant.id,
            actor_id=actor.user.id,
            actor_name=actor.user.name,
            action=action,
            target_id=target_id,
            target_name=target_name,
            details=(details or {})
            | ({"actor_scope": "platform"} if actor.member.source == "platform" else {}),
            result=result,
        )
    )


async def protect_admin(request: Request, db: AsyncSession, member: Membership) -> None:
    candidates = (
        (
            await db.execute(
                select(LoginIdentity)
                .join(Membership, Membership.user_id == LoginIdentity.user_id)
                .where(
                    Membership.tenant_id == member.tenant_id,
                    Membership.role == "administrator",
                    Membership.status == "active",
                    Membership.id != member.id,
                    Membership.source != "platform",
                    LoginIdentity.issuer == provider(request).settings.oidc_issuer,
                )
            )
        )
        .scalars()
        .all()
    )
    for identity in candidates:
        if await provider(request).user_enabled(identity.subject):
            return
    raise HTTPException(409, "不能变更最后一名有效管理员，请先指定另一位正常成员为管理员")


def membership_state(
    tenant: Tenant | None, member: Membership | None, authenticated_at: datetime | None
) -> str | None:
    if not tenant or not member or member.source == "platform":
        return "no_membership"
    if not tenant.active:
        return "organization_unavailable"
    if member.status != "active":
        return "member_removed" if member.status == "removed" else "member_suspended"
    if member.revoked_at and (not authenticated_at or authenticated_at <= member.revoked_at):
        return "reauthentication_required"
    return None
