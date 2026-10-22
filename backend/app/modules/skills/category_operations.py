"""Shared category operations; callers own authorization and commit."""

from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.members.service import BusinessActor, record
from app.modules.skills import service
from app.modules.skills.categories import (
    CategoryDelete,
    CategoryMove,
    CategoryName,
    CategoryRename,
    ManagedSkillCategory,
    category_rows,
    require_category,
)
from app.modules.skills.models import Skill, SkillCategoryRecord


async def listing(db: AsyncSession, actor: BusinessActor) -> list[ManagedSkillCategory]:
    counts = {
        key: count
        for (key, count) in (
            await db.execute(
                select(Skill.category, func.count())
                .where(Skill.tenant_id == actor.tenant.id)
                .group_by(Skill.category)
            )
        ).all()
    }
    return [
        ManagedSkillCategory(
            id=row.id,
            name=row.name,
            revision=row.revision,
            system=row.id == "uncategorized",
            count=counts.get(row.id, 0),
        )
        for row in await category_rows(db, actor.tenant.id)
    ]


def mutable(row: SkillCategoryRecord, revision: int) -> None:
    if row.id == "uncategorized":
        raise HTTPException(409, "未分类是系统类别，不能修改、排序或删除")
    if row.revision != revision:
        raise HTTPException(409, "类别已被修改，请刷新后重试")


async def unique_name(db: AsyncSession, tenant_id: UUID, name: str, exclude: str = "") -> None:
    if await db.scalar(
        select(SkillCategoryRecord.id).where(
            SkillCategoryRecord.tenant_id == tenant_id,
            SkillCategoryRecord.name_key == name.casefold(),
            SkillCategoryRecord.id != exclude,
        )
    ):
        raise HTTPException(409, "类别名称已存在")


async def categories(actor: BusinessActor, request: Request, db: DB) -> list[ManagedSkillCategory]:
    service.administrator(actor)
    return await listing(db, actor)


async def create(
    actor: BusinessActor, request: Request, db: DB, body: CategoryName
) -> list[ManagedSkillCategory]:
    service.administrator(actor)
    await unique_name(db, actor.tenant.id, body.name)
    rows = await category_rows(db, actor.tenant.id)
    key = str(uuid4())
    db.add(
        SkillCategoryRecord(
            tenant_id=actor.tenant.id,
            id=key,
            name=body.name,
            name_key=body.name.casefold(),
            position=max((r.position for r in rows), default=0) + 1,
        )
    )
    record(db, actor, "skills.category.create", actor.tenant.id, body.name, {"category_id": key})
    await db.flush()
    result = await listing(db, actor)
    await db.flush()
    return result


async def rename(
    actor: BusinessActor, category_id: str, request: Request, db: DB, body: CategoryRename
) -> list[ManagedSkillCategory]:
    service.administrator(actor)
    row = await require_category(db, actor.tenant.id, category_id)
    mutable(row, body.revision)
    await unique_name(db, actor.tenant.id, body.name, row.id)
    old_name = row.name
    (row.name, row.name_key) = (body.name, body.name.casefold())
    row.revision += 1
    record(
        db,
        actor,
        "skills.category.rename",
        actor.tenant.id,
        body.name,
        {"category_id": row.id, "previous_name": old_name},
    )
    await db.flush()
    result = await listing(db, actor)
    await db.flush()
    return result


async def move(
    actor: BusinessActor, category_id: str, request: Request, db: DB, body: CategoryMove
) -> list[ManagedSkillCategory]:
    service.administrator(actor)
    row = await require_category(db, actor.tenant.id, category_id)
    mutable(row, body.revision)
    rows = [r for r in await category_rows(db, actor.tenant.id) if r.id != "uncategorized"]
    index = next(i for (i, r) in enumerate(rows) if r.id == category_id)
    destination = index + (-1 if body.direction == "up" else 1)
    if destination < 0 or destination >= len(rows):
        raise HTTPException(409, "已到类别列表边界，请刷新后重试")
    other = rows[destination]
    (row.position, other.position) = (other.position, row.position)
    row.revision += 1
    other.revision += 1
    record(
        db,
        actor,
        "skills.category.move",
        actor.tenant.id,
        row.name,
        {"category_id": row.id, "direction": body.direction},
    )
    await db.flush()
    result = await listing(db, actor)
    await db.flush()
    return result


async def delete(
    actor: BusinessActor, category_id: str, request: Request, db: DB, body: CategoryDelete
) -> Message:
    service.administrator(actor)
    row = await require_category(db, actor.tenant.id, category_id)
    mutable(row, body.revision)
    if body.target_id == category_id:
        raise HTTPException(422, "请选择其他类别接收技能")
    await require_category(db, actor.tenant.id, body.target_id)
    conditions = (Skill.tenant_id == actor.tenant.id, Skill.category == category_id)
    count = await db.scalar(select(func.count()).select_from(Skill).where(*conditions)) or 0
    if count != body.count:
        raise HTTPException(409, "关联技能数量已变化，请刷新后重新确认")
    await db.execute(
        update(Skill)
        .where(*conditions)
        .values(category=body.target_id, revision=Skill.revision + 1)
    )
    await db.delete(row)
    record(
        db,
        actor,
        "skills.category.delete",
        actor.tenant.id,
        row.name,
        {"category_id": row.id, "target_id": body.target_id, "skill_count": str(count)},
    )
    await db.flush()
    return Message(message="类别已删除，关联技能已迁移" if count else "类别已删除")
