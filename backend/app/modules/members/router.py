from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, now, provider
from app.modules.members.models import Membership
from app.modules.members.provisioning import create_member
from app.modules.members.schemas import (
    MemberChange,
    MemberCreate,
    MemberCreated,
    MemberPage,
    MemberSelectionQuery,
    MemberView,
)
from app.modules.members.service import access, member_view, protect_admin, record
from app.modules.users.models import LoginIdentity, User

router = APIRouter(prefix="/api/v1/enterprises/{tenant_id}/members", tags=["members"])


@router.post("", response_model=MemberCreated)
async def create(
    tenant_id: UUID, payload: MemberCreate, request: Request, db: DB, _: Mutation
) -> MemberCreated:
    return await create_member(tenant_id, payload, request, db)


@router.get("", response_model=MemberPage)
async def members(
    tenant_id: UUID,
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=200),
    role: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
) -> MemberPage:
    actor = await access(request, db, tenant_id)
    filters = [Membership.tenant_id == tenant_id, Membership.source != "platform"]
    filters.append(Membership.status == status if status else Membership.status != "removed")
    if role:
        filters.append(Membership.role == role)
    if q.strip():
        needle = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(or_(User.name.ilike(needle), User.email.ilike(needle)))
    query = select(Membership, User).join(User).where(*filters)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.execute(
            query.order_by(Membership.joined_at, Membership.id).offset((page - 1) * 20).limit(20)
        )
    ).all()
    return MemberPage(
        items=[member_view(m, u, actor.user) for m, u in rows], total=total, page=page
    )


@router.post("/selection", response_model=MemberPage)
async def selected_members(
    tenant_id: UUID, payload: MemberSelectionQuery, request: Request, db: DB, _: Mutation
) -> MemberPage:
    """Resolve a bounded selection without exposing another tenant's directory."""
    actor = await access(request, db, tenant_id)
    query = (
        select(Membership, User)
        .join(User)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.source != "platform",
            Membership.id.in_(payload.member_ids),
        )
    )
    if payload.q.strip():
        needle = (
            "%"
            + payload.q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            + "%"
        )
        query = query.where(or_(User.name.ilike(needle), User.email.ilike(needle)))
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.execute(
            query.order_by(Membership.joined_at, Membership.id)
            .offset((payload.page - 1) * 20)
            .limit(20)
        )
    ).all()
    return MemberPage(
        items=[member_view(m, u, actor.user) for m, u in rows], total=total, page=payload.page
    )


@router.get("/{member_id}", response_model=MemberView)
async def detail(tenant_id: UUID, member_id: UUID, request: Request, db: DB) -> MemberView:
    actor = await access(request, db, tenant_id)
    row = (
        await db.execute(
            select(Membership, User)
            .join(User)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.source != "platform",
                Membership.id == member_id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(404, "成员不存在")
    return member_view(row[0], row[1], actor.user)


@router.patch("/{member_id}", response_model=MemberView)
async def change(
    tenant_id: UUID, member_id: UUID, payload: MemberChange, request: Request, db: DB, _: Mutation
) -> MemberView:
    actor = await access(request, db, tenant_id, write=True)
    member = await db.scalar(
        select(Membership)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.source != "platform",
            Membership.id == member_id,
        )
        .execution_options(populate_existing=True)
    )
    if member is None:
        raise HTTPException(404, "成员不存在")
    if member.version != payload.version:
        raise HTTPException(409, "成员状态已变化，请刷新详情后重试")
    if member.status == "removed":
        raise HTTPException(409, "成员已退出，再次加入需要新的邀请")
    old_role, old_status = member.role, member.status
    new_role, new_status = old_role, old_status
    if payload.action == "role":
        if member.status != "active" or payload.role is None:
            raise HTTPException(409, "只能调整正常成员的角色")
        new_role = payload.role
    else:
        new_status = {"pause": "paused", "restore": "active", "remove": "removed"}[payload.action]
    if (new_role, new_status) == (old_role, old_status):
        raise HTTPException(409, "成员已处于此状态，请刷新详情")
    if (
        old_role == "administrator"
        and old_status == "active"
        and (new_role != old_role or new_status != "active")
    ):
        await protect_admin(request, db, member)
    if new_status == "active" and (payload.action == "restore" or new_role == "administrator"):
        identity = await db.scalar(
            select(LoginIdentity).where(
                LoginIdentity.user_id == member.user_id,
                LoginIdentity.issuer == provider(request).settings.oidc_issuer,
            )
        )
        if not identity or not await provider(request).user_enabled(identity.subject):
            raise HTTPException(409, "该成员的登录身份不可用，无法恢复或授予管理权限")
    member.role, member.status = new_role, new_status
    member.version += 1
    if new_status != "active":
        member.revoked_at = now()
    target = await db.get(User, member.user_id)
    assert target is not None
    record(
        db,
        actor,
        "member." + payload.action,
        member.id,
        target.name,
        {
            "before_role": old_role,
            "after_role": new_role,
            "before_status": old_status,
            "after_status": new_status,
            "reason": payload.reason.strip(),
        },
    )
    await db.commit()
    return member_view(member, target, actor.user)
