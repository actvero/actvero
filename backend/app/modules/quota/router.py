from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, now
from app.modules.members.models import Membership
from app.modules.members.service import Access, member_avatar_url, record
from app.modules.quota.models import QuotaAssignment, QuotaPolicy
from app.modules.quota.schemas import (
    MemberQuotaMatch,
    PolicyMatch,
    QuotaArchive,
    QuotaAssignmentInput,
    QuotaMatchPage,
    QuotaPolicyInput,
    QuotaPolicyPage,
    QuotaPolicyUpdate,
    QuotaPolicyView,
)
from app.modules.quota.service import configured_policy
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/quota", tags=["quota-policies"])


async def administrator(request: Request, db: DB, *, write: bool = False) -> Access:
    actor = await own_access(request, db, write=write)
    if actor.member.role != "administrator":
        raise HTTPException(403, "仅管理员可以管理额度策略")
    return actor


def view(row: QuotaPolicy) -> QuotaPolicyView:
    return QuotaPolicyView(**{k: getattr(row, k) for k in QuotaPolicyView.model_fields})


async def get_policy(db: DB, tenant_id: UUID, policy_id: UUID, version: int) -> QuotaPolicy:
    row = await db.scalar(
        select(QuotaPolicy)
        .where(QuotaPolicy.tenant_id == tenant_id, QuotaPolicy.id == policy_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "策略不存在")
    if row.version != version:
        raise HTTPException(409, "策略已被修改，请关闭并重新打开")
    return row


async def configure(db: DB, actor: Access, row: QuotaPolicy, body: QuotaPolicyInput) -> None:
    policies = list(
        await db.scalars(
            select(QuotaPolicy).where(
                QuotaPolicy.tenant_id == actor.tenant.id,
                QuotaPolicy.archived.is_(False),
                QuotaPolicy.id != row.id,
            )
        )
    )
    if any(p.name == body.name for p in policies):
        raise HTTPException(409, "策略名称已存在")
    if body.is_default and any(p.is_default for p in policies):
        raise HTTPException(409, "组织已存在默认策略")
    row.name, row.is_default, row.mode = body.name, body.is_default, body.mode
    row.rules = [r.model_dump(mode="json") for r in body.rules]
    row.updated_at = now()


@router.get("/policies", response_model=QuotaPolicyPage)
async def listing(
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=100),
    state: Literal["current", "archived"] = "current",
    assignable_only: bool = False,
    page: int = Query(default=1, ge=1),
) -> QuotaPolicyPage:
    actor = await administrator(request, db)
    filters = [
        QuotaPolicy.tenant_id == actor.tenant.id,
        QuotaPolicy.archived == (state == "archived"),
    ]
    if q.strip():
        filters.append(QuotaPolicy.name.icontains(q.strip(), autoescape=True))
    if assignable_only:
        filters.append(QuotaPolicy.is_default.is_(False))
    total = await db.scalar(select(func.count()).select_from(QuotaPolicy).where(*filters)) or 0
    rows = await db.scalars(
        select(QuotaPolicy)
        .where(*filters)
        .order_by(QuotaPolicy.is_default.desc(), QuotaPolicy.created_at.desc(), QuotaPolicy.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    default = await db.scalar(
        select(QuotaPolicy).where(
            QuotaPolicy.tenant_id == actor.tenant.id, QuotaPolicy.is_default.is_(True)
        )
    )
    return QuotaPolicyPage(
        items=[view(r) for r in rows],
        total=total,
        has_default=default is not None,
    )


@router.post("/policies", response_model=QuotaPolicyView)
async def create(request: Request, db: DB, body: QuotaPolicyInput, _: Mutation) -> QuotaPolicyView:
    actor = await administrator(request, db, write=True)
    row = QuotaPolicy(id=uuid4(), tenant_id=actor.tenant.id)
    await configure(db, actor, row, body)
    db.add(row)
    await db.flush()
    record(db, actor, "quota.policy.create", row.id, row.name)
    result = view(row)
    await db.commit()
    return result


@router.put("/policies/{policy_id}", response_model=QuotaPolicyView)
async def update(
    policy_id: UUID, request: Request, db: DB, body: QuotaPolicyUpdate, _: Mutation
) -> QuotaPolicyView:
    actor = await administrator(request, db, write=True)
    row = await get_policy(db, actor.tenant.id, policy_id, body.version)
    if row.archived:
        raise HTTPException(409, "请先恢复策略")
    if row.is_default != body.is_default:
        raise HTTPException(422, "不能改变默认策略身份")
    await configure(db, actor, row, body)
    row.version += 1
    record(db, actor, "quota.policy.update", row.id, row.name)
    result = view(row)
    await db.commit()
    return result


@router.put("/policies/{policy_id}/archive", response_model=QuotaPolicyView)
async def archive(
    policy_id: UUID, request: Request, db: DB, body: QuotaArchive, _: Mutation
) -> QuotaPolicyView:
    actor = await administrator(request, db, write=True)
    row = await get_policy(db, actor.tenant.id, policy_id, body.version)
    if row.is_default:
        raise HTTPException(409, "默认策略不能归档")
    if body.archived and await db.scalar(
        select(QuotaAssignment.member_id)
        .join(Membership, Membership.id == QuotaAssignment.member_id)
        .where(
            QuotaAssignment.tenant_id == actor.tenant.id,
            QuotaAssignment.policy_id == row.id,
            Membership.status != "removed",
        )
        .limit(1)
    ):
        raise HTTPException(409, "策略仍有分配成员，请先调整成员策略")
    if not body.archived:
        await configure(
            db,
            actor,
            row,
            QuotaPolicyInput.model_validate(
                {
                    "name": row.name,
                    "is_default": row.is_default,
                    "mode": row.mode,
                    "rules": row.rules,
                }
            ),
        )
    row.archived, row.updated_at = body.archived, now()
    row.version += 1
    record(
        db,
        actor,
        "quota.policy.archive" if body.archived else "quota.policy.restore",
        row.id,
        row.name,
    )
    result = view(row)
    await db.commit()
    return result


@router.get("/matches", response_model=QuotaMatchPage, summary="当前成员策略匹配，不包含消费或余额")
async def matches(
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
) -> QuotaMatchPage:
    actor = await administrator(request, db)
    filters = [Membership.tenant_id == actor.tenant.id, Membership.status.in_(("active", "paused"))]
    if q.strip():
        filters.append(
            or_(
                User.name.icontains(q.strip(), autoescape=True),
                User.email.icontains(q.strip(), autoescape=True),
            )
        )
    query = select(Membership, User).join(User).where(*filters)
    total = await db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = (
        await db.execute(
            query.order_by(Membership.joined_at, Membership.id).offset((page - 1) * 20).limit(20)
        )
    ).all()
    result = []
    for member, user in rows:
        result.append(await member_match(db, actor.tenant.id, member, user))
    return QuotaMatchPage(items=result, total=total)


async def member_match(db: DB, tenant_id: UUID, member: Membership, user: User) -> MemberQuotaMatch:
    selected = await configured_policy(db, tenant_id, member.id)
    assignment = await db.get(QuotaAssignment, member.id, populate_existing=True)
    choice = (
        PolicyMatch.model_validate(
            {
                "id": selected.id,
                "name": selected.name,
                "mode": selected.mode,
                "is_default": selected.is_default,
            }
        )
        if selected
        else None
    )
    return MemberQuotaMatch.model_validate(
        {
            "member_id": member.id,
            "name": user.name,
            "email": user.email,
            "role": member.role,
            "status": member.status,
            "avatar_url": member_avatar_url(member, user),
            "assigned": choice if assignment and assignment.policy_id else None,
            "assignment_version": assignment.version if assignment else 0,
            "selected": choice,
            "rules": selected.rules if selected else [],
        }
    )


@router.put("/members/{member_id}/assignment", response_model=MemberQuotaMatch)
async def assign(
    member_id: UUID, request: Request, db: DB, body: QuotaAssignmentInput, _: Mutation
) -> MemberQuotaMatch:
    actor = await administrator(request, db, write=True)
    pair = (
        await db.execute(
            select(Membership, User)
            .join(User)
            .where(
                Membership.tenant_id == actor.tenant.id,
                Membership.id == member_id,
                Membership.status != "removed",
            )
        )
    ).one_or_none()
    if pair is None:
        raise HTTPException(404, "成员不存在")
    member, user = pair
    row = await db.get(QuotaAssignment, member_id, populate_existing=True)
    if body.version != (row.version if row else 0):
        raise HTTPException(409, "成员额度策略已被修改，请刷新后重试")
    policy_id = body.policy_id
    if policy_id is not None:
        policy = await db.scalar(
            select(QuotaPolicy).where(
                QuotaPolicy.id == policy_id,
                QuotaPolicy.tenant_id == actor.tenant.id,
                QuotaPolicy.archived.is_(False),
            )
        )
        if policy is None:
            raise HTTPException(404, "策略不存在或已归档")
        if member.status != "active":
            raise HTTPException(422, "只能向正常成员分配策略")
        if policy.is_default:
            policy_id = None
    previous = str(row.policy_id) if row and row.policy_id else "default"
    if row is None:
        row = QuotaAssignment(member_id=member_id, tenant_id=actor.tenant.id, version=1)
        db.add(row)
    else:
        row.version += 1
    row.policy_id, row.updated_at = policy_id, now()
    await db.flush()
    record(
        db,
        actor,
        "quota.member.assign",
        member_id,
        user.name,
        {"before_policy": previous, "after_policy": str(policy_id) if policy_id else "default"},
    )
    result = await member_match(db, actor.tenant.id, member, user)
    await db.commit()
    return result
