from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import delete, func, or_, select

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB
from app.modules.departments.access import DepartmentAccess, load_access, validate_departments
from app.modules.departments.models import Department, DepartmentMember
from app.modules.departments.schemas import (
    DepartmentInput,
    DepartmentScopeMember,
    DepartmentScopePage,
    DepartmentScopePreview,
    DepartmentUpdate,
    DepartmentView,
    MemberDepartments,
)
from app.modules.members.models import Membership
from app.modules.members.service import Access, access, record
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/enterprises/{tenant_id}", tags=["departments"])


async def administrator(
    request: Request, db: DB, tenant_id: UUID, *, write: bool = False
) -> Access:
    return await access(request, db, tenant_id, write=write, allow_platform_elevation=False)


async def department_rows(db: DB, tenant_id: UUID) -> list[Department]:
    return list(
        await db.scalars(
            select(Department)
            .where(Department.tenant_id == tenant_id)
            .order_by(Department.sort_order, Department.name, Department.id)
        )
    )


def check_parent(
    rows: dict[UUID, Department], department_id: UUID | None, parent_id: UUID | None
) -> None:
    visited = {department_id}
    while parent_id is not None:
        if parent_id in visited:
            raise HTTPException(422, "不能将部门移入自身或下级部门")
        parent = rows.get(parent_id)
        if parent is None or parent.archived:
            raise HTTPException(422, "上级部门不存在或已归档")
        visited.add(parent_id)
        parent_id = parent.parent_id


def check_name(
    rows: dict[UUID, Department], payload: DepartmentInput, department_id: UUID | None = None
) -> None:
    if any(
        row.id != department_id
        and not row.archived
        and row.parent_id == payload.parent_id
        and row.name == payload.name
        for row in rows.values()
    ):
        raise HTTPException(409, "同一上级下已有同名部门")


@router.get("/departments", response_model=list[DepartmentView])
async def departments(tenant_id: UUID, request: Request, db: DB) -> list[DepartmentView]:
    await administrator(request, db, tenant_id)
    return [DepartmentView.model_validate(row) for row in await department_rows(db, tenant_id)]


@router.post("/departments/scope-preview", response_model=DepartmentScopePage)
async def preview_scope(
    tenant_id: UUID, payload: DepartmentScopePreview, request: Request, db: DB, _: Mutation
) -> DepartmentScopePage:
    await administrator(request, db, tenant_id)
    active = select(Department.id).where(
        Department.tenant_id == tenant_id, Department.archived.is_(False)
    )
    nodes = active.where(
        Department.id.in_(
            [
                grant.department_id
                for grant in payload.department_grants
                if grant.include_descendants
            ]
        )
    ).cte(recursive=True)
    nodes = nodes.union(active.join(nodes, Department.parent_id == nodes.c.id))
    direct_nodes = active.where(
        Department.id.in_([grant.department_id for grant in payload.department_grants])
    )
    department_members = select(DepartmentMember.member_id).where(
        DepartmentMember.tenant_id == tenant_id,
        or_(
            DepartmentMember.department_id.in_(direct_nodes),
            DepartmentMember.department_id.in_(select(nodes.c.id)),
        ),
    )
    candidates = (
        select(Membership.id, User.name)
        .join(User)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
            Membership.source != "platform",
            or_(Membership.id.in_(payload.member_ids), Membership.id.in_(department_members)),
        )
    )
    total = await db.scalar(select(func.count()).select_from(candidates.subquery())) or 0
    rows = (
        await db.execute(
            candidates.order_by(User.name, Membership.id).offset((payload.page - 1) * 20).limit(20)
        )
    ).all()
    scopes = await load_access(db, tenant_id, [row.id for row in rows])
    return DepartmentScopePage(
        page=payload.page,
        total=total,
        items=[
            DepartmentScopeMember(
                id=row.id,
                name=row.name,
                direct=row.id in payload.member_ids,
                department_ids=[
                    grant.department_id
                    for grant in payload.department_grants
                    if scopes.get(row.id, DepartmentAccess()).matches([grant])
                ],
            )
            for row in rows
        ],
    )


@router.post("/departments", response_model=DepartmentView, status_code=201)
async def create(
    tenant_id: UUID, payload: DepartmentInput, request: Request, db: DB, _: Mutation
) -> DepartmentView:
    actor = await administrator(request, db, tenant_id, write=True)
    rows = {row.id: row for row in await department_rows(db, tenant_id)}
    check_parent(rows, None, payload.parent_id)
    check_name(rows, payload)
    row = Department(tenant_id=tenant_id, **payload.model_dump())
    db.add(row)
    await db.flush()
    record(db, actor, "department.create", row.id, row.name)
    view = DepartmentView.model_validate(row)
    await db.commit()
    return view


@router.put("/departments/{department_id}", response_model=DepartmentView)
async def update(
    tenant_id: UUID,
    department_id: UUID,
    payload: DepartmentUpdate,
    request: Request,
    db: DB,
    _: Mutation,
) -> DepartmentView:
    actor = await administrator(request, db, tenant_id, write=True)
    rows = {row.id: row for row in await department_rows(db, tenant_id)}
    row = rows.get(department_id)
    if row is None:
        raise HTTPException(404, "部门不存在")
    if row.version != payload.version:
        raise HTTPException(409, "部门已被修改，请刷新后重试")
    if payload.archived:
        if any(child.parent_id == row.id and not child.archived for child in rows.values()):
            raise HTTPException(409, "请先移动或归档下级部门")
        assigned = await db.scalar(
            select(DepartmentMember.member_id)
            .where(
                DepartmentMember.tenant_id == tenant_id, DepartmentMember.department_id == row.id
            )
            .limit(1)
        )
        if assigned is not None:
            raise HTTPException(409, "请先调整该部门的成员归属")
    else:
        check_parent(rows, row.id, payload.parent_id)
        check_name(rows, payload, row.id)
    row.name, row.sort_order = payload.name, payload.sort_order
    if not payload.archived:
        row.parent_id = payload.parent_id
    row.archived = payload.archived
    row.version += 1
    record(
        db, actor, "department.archive" if row.archived else "department.update", row.id, row.name
    )
    view = DepartmentView.model_validate(row)
    await db.commit()
    return view


async def find_member(db: DB, tenant_id: UUID, member_id: UUID) -> Membership:
    row = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.id == member_id,
            Membership.source != "platform",
            Membership.status != "removed",
        )
    )
    if row is None:
        raise HTTPException(404, "成员不存在")
    return row


@router.get("/members/{member_id}/departments", response_model=MemberDepartments)
async def member_departments(
    tenant_id: UUID, member_id: UUID, request: Request, db: DB
) -> MemberDepartments:
    await administrator(request, db, tenant_id)
    member = await find_member(db, tenant_id, member_id)
    rows = list(
        await db.scalars(
            select(DepartmentMember)
            .where(DepartmentMember.tenant_id == tenant_id, DepartmentMember.member_id == member_id)
            .order_by(DepartmentMember.department_id)
        )
    )
    return MemberDepartments(
        department_ids=[row.department_id for row in rows],
        primary_department_id=next((row.department_id for row in rows if row.is_primary), None),
        version=member.version,
    )


@router.put("/members/{member_id}/departments", response_model=MemberDepartments)
async def assign(
    tenant_id: UUID,
    member_id: UUID,
    payload: MemberDepartments,
    request: Request,
    db: DB,
    _: Mutation,
) -> MemberDepartments:
    actor = await administrator(request, db, tenant_id, write=True)
    member = await find_member(db, tenant_id, member_id)
    if payload.version != member.version:
        raise HTTPException(409, "成员已被修改，请刷新后重试")
    await validate_departments(db, tenant_id, payload.department_ids)
    await db.execute(
        delete(DepartmentMember).where(
            DepartmentMember.tenant_id == tenant_id, DepartmentMember.member_id == member_id
        )
    )
    db.add_all(
        DepartmentMember(
            tenant_id=tenant_id,
            member_id=member_id,
            department_id=department_id,
            is_primary=department_id == payload.primary_department_id,
        )
        for department_id in payload.department_ids
    )
    member.version += 1
    record(
        db,
        actor,
        "member.departments",
        member_id,
        "成员部门",
        {
            "department_ids": ",".join(str(item) for item in payload.department_ids),
            "primary_department_id": str(payload.primary_department_id or ""),
        },
    )
    result = payload.model_copy(update={"version": member.version})
    await db.commit()
    return result
