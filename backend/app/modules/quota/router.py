from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, now
from app.modules.members.models import Membership
from app.modules.members.service import Access, record
from app.modules.quota.models import QuotaPolicy
from app.modules.quota.schemas import (
    CalendarWeek,
    MemberQuotaMatch,
    PolicyMatch,
    QuotaArchive,
    QuotaMatchPage,
    QuotaPolicyInput,
    QuotaPolicyPage,
    QuotaPolicyUpdate,
    QuotaPolicyView,
)
from app.modules.quota.service import matching_policies
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
    if any(p.priority == body.priority for p in policies):
        raise HTTPException(409, "优先级已被其他策略使用")
    if any(p.name == body.name for p in policies):
        raise HTTPException(409, "策略名称已存在")
    if body.priority > 0 and not any(p.priority == 0 for p in policies):
        raise HTTPException(409, "请先设置默认策略")
    if body.member_ids:
        # Retain previously assigned paused members on edits; they never match until active.
        existing = set(row.member_ids or [])
        members = list(
            await db.scalars(
                select(Membership).where(
                    Membership.tenant_id == actor.tenant.id, Membership.id.in_(body.member_ids)
                )
            )
        )
        if len(members) != len(body.member_ids) or any(
            m.status == "removed" or (m.status != "active" and str(m.id) not in existing)
            for m in members
        ):
            raise HTTPException(422, "包含不可选成员，请检查成员范围")
    row.name, row.priority = body.name, body.priority
    row.member_ids = [str(m) for m in body.member_ids]
    row.rules = [r.model_dump(mode="json") for r in body.rules]
    row.updated_at = now()


@router.get("/policies", response_model=QuotaPolicyPage)
async def listing(
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=100),
    state: Literal["current", "archived"] = "current",
    page: int = Query(default=1, ge=1),
) -> QuotaPolicyPage:
    actor = await administrator(request, db)
    filters = [
        QuotaPolicy.tenant_id == actor.tenant.id,
        QuotaPolicy.archived == (state == "archived"),
    ]
    if q.strip():
        filters.append(QuotaPolicy.name.icontains(q.strip(), autoescape=True))
    total = await db.scalar(select(func.count()).select_from(QuotaPolicy).where(*filters)) or 0
    rows = await db.scalars(
        select(QuotaPolicy)
        .where(*filters)
        .order_by(QuotaPolicy.priority.desc(), QuotaPolicy.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    default = await db.scalar(
        select(QuotaPolicy).where(
            QuotaPolicy.tenant_id == actor.tenant.id, QuotaPolicy.priority == 0
        )
    )
    return QuotaPolicyPage(
        items=[view(r) for r in rows],
        total=total,
        has_default=default is not None,
        default_timezone=next(
            (rule.timezone for rule in view(default).rules if isinstance(rule, CalendarWeek)),
            None,
        )
        if default is not None
        else None,
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
    if (row.priority == 0) != (body.priority == 0):
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
    if row.priority == 0:
        raise HTTPException(409, "默认策略不能归档")
    if not body.archived:
        await configure(
            db,
            actor,
            row,
            QuotaPolicyInput(
                name=row.name, priority=row.priority, member_ids=row.member_ids, rules=row.rules
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
    filters = [Membership.tenant_id == actor.tenant.id, Membership.status == "active"]
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
        policies = await matching_policies(db, actor.tenant.id, member.id)
        matched = [PolicyMatch(id=p.id, name=p.name, priority=p.priority) for p in policies]
        result.append(
            MemberQuotaMatch(
                member_id=member.id,
                name=user.name,
                email=user.email,
                role=member.role,
                matched=matched,
                selected=matched[0] if matched else None,
                rules=policies[0].rules if policies else [],
            )
        )
    return QuotaMatchPage(items=result, total=total)
