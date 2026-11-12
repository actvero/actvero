from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import ColumnElement, false, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.modules.departments.models import Department, DepartmentMember
from app.modules.departments.schemas import DepartmentGrant


@dataclass(frozen=True)
class DepartmentAccess:
    direct: frozenset[str] = frozenset()
    ancestors: frozenset[str] = frozenset()

    def matches(self, grants: Sequence[dict[str, Any] | DepartmentGrant] | None) -> bool:
        for grant in grants or ():
            if isinstance(grant, DepartmentGrant):
                node, include_descendants = str(grant.department_id), grant.include_descendants
            else:
                node = grant["department_id"]
                include_descendants = grant.get("include_descendants") is True
            if node in self.direct or include_descendants and node in self.ancestors:
                return True
        return False

    def predicate(self, column: InstrumentedAttribute[list[dict[str, Any]]]) -> ColumnElement[bool]:
        return or_(
            false(),
            *(column.contains([{"department_id": node}]) for node in self.direct),
            *(
                column.contains([{"department_id": node, "include_descendants": True}])
                for node in self.ancestors - self.direct
            ),
        )


async def load_access(
    db: AsyncSession, tenant_id: UUID, member_ids: list[UUID]
) -> dict[UUID, DepartmentAccess]:
    if not member_ids:
        return {}
    nodes = (
        select(
            DepartmentMember.member_id,
            Department.id.label("department_id"),
            Department.parent_id,
            literal(True).label("direct"),
        )
        .select_from(DepartmentMember)
        .join(Department, Department.id == DepartmentMember.department_id)
        .where(
            DepartmentMember.tenant_id == tenant_id,
            DepartmentMember.member_id.in_(member_ids),
            Department.tenant_id == tenant_id,
            Department.archived.is_(False),
        )
        .cte(recursive=True)
    )
    nodes = nodes.union(
        select(nodes.c.member_id, Department.id, Department.parent_id, literal(False))
        .select_from(nodes)
        .join(Department, Department.id == nodes.c.parent_id)
        .where(Department.tenant_id == tenant_id, Department.archived.is_(False))
    )
    direct: dict[UUID, set[str]] = {}
    ancestors: dict[UUID, set[str]] = {}
    for member, department, _, is_direct in (await db.execute(select(nodes))).all():
        (direct if is_direct else ancestors).setdefault(member, set()).add(str(department))
    return {
        member: DepartmentAccess(frozenset(direct[member]), frozenset(ancestors.get(member, ())))
        for member in direct
    }


async def validate_departments(
    db: AsyncSession, tenant_id: UUID, department_ids: list[UUID]
) -> None:
    if not department_ids:
        return
    found = set(
        await db.scalars(
            select(Department.id).where(
                Department.tenant_id == tenant_id,
                Department.id.in_(department_ids),
                Department.archived.is_(False),
            )
        )
    )
    if found != set(department_ids):
        raise HTTPException(422, "请选择当前组织的有效部门")


async def resolve_grants(
    db: AsyncSession,
    tenant_id: UUID,
    audience: str,
    member_ids: list[UUID],
    grants: list[DepartmentGrant] | None,
    current: list[dict[str, Any]] | None = None,
    *,
    require_selection: bool = True,
) -> list[dict[str, Any]]:
    if grants is None and current and audience != "selected":
        raise HTTPException(409, "请使用新版后台调整包含部门的使用范围")
    if grants is None:
        result = current or []
    else:
        ids = [grant.department_id for grant in grants]
        if len(set(ids)) != len(ids):
            raise HTTPException(422, "不能重复授权同一个部门")
        await validate_departments(db, tenant_id, ids)
        result = [grant.model_dump(mode="json") for grant in grants]
    if result and audience != "selected":
        raise HTTPException(422, "请选择指定范围后添加部门授权")
    if require_selection and audience == "selected" and not (member_ids or result):
        raise HTTPException(422, "请选择至少一个部门或成员")
    return result
