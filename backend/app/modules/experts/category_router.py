from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.experts import service
from app.modules.experts.categories import (
    ExpertCategoryDelete,
    ExpertCategoryMove,
    ExpertCategoryName,
    ExpertCategoryRename,
    ManagedExpertCategory,
    category_rows,
    require_category,
)
from app.modules.experts.models import ExpertCategoryRecord, ExpertRecord
from app.modules.members.service import BusinessActor, record

router = APIRouter(prefix="/categories")


async def listing(db: AsyncSession, actor: BusinessActor) -> list[ManagedExpertCategory]:
    counts = {
        key: count
        for key, count in (
            (
                await db.execute(
                    select(ExpertRecord.category, func.count())
                    .where(ExpertRecord.tenant_id == actor.tenant.id)
                    .group_by(ExpertRecord.category)
                )
            ).all()
        )
    }
    return [
        ManagedExpertCategory(
            id=row.id,
            name=row.name,
            revision=row.revision,
            system=row.id == "uncategorized",
            count=counts.get(row.id, 0),
        )
        for row in await category_rows(db, actor.tenant.id)
    ]


def mutable(row: ExpertCategoryRecord, revision: int) -> None:
    if row.id == "uncategorized":
        raise HTTPException(409, "未分类是系统类别，不能修改、排序或删除")
    if row.revision != revision:
        raise HTTPException(409, "类别已被修改，请刷新后重试")


async def unique_name(db: AsyncSession, tenant_id: UUID, name: str, exclude: str = "") -> None:
    if await db.scalar(
        select(ExpertCategoryRecord.id).where(
            ExpertCategoryRecord.tenant_id == tenant_id,
            ExpertCategoryRecord.name_key == name.casefold(),
            ExpertCategoryRecord.id != exclude,
        )
    ):
        raise HTTPException(409, "类别名称已存在")


@router.get(
    "", response_model=list[ManagedExpertCategory], summary="管理员读取动态类别与全部专家数量"
)
async def categories(request: Request, db: DB) -> list[ManagedExpertCategory]:
    actor = await own_access(request, db)
    service.administrator(actor)
    return await listing(db, actor)


@router.post("", response_model=list[ManagedExpertCategory], summary="管理员新增类别")
async def create(
    request: Request, db: DB, body: ExpertCategoryName, _csrf: Mutation
) -> list[ManagedExpertCategory]:
    actor = await own_access(request, db, write=True)
    service.administrator(actor)
    await unique_name(db, actor.tenant.id, body.name)
    rows = await category_rows(db, actor.tenant.id)
    key = str(uuid4())
    db.add(
        ExpertCategoryRecord(
            tenant_id=actor.tenant.id,
            id=key,
            name=body.name,
            name_key=body.name.casefold(),
            position=max((r.position for r in rows), default=0) + 1,
        )
    )
    record(db, actor, "experts.category.create", actor.tenant.id, body.name, {"category_id": key})
    await db.flush()
    result = await listing(db, actor)
    await db.commit()
    return result


@router.patch(
    "/{category_id}", response_model=list[ManagedExpertCategory], summary="管理员改名，保留类别 ID"
)
async def rename(
    category_id: str, request: Request, db: DB, body: ExpertCategoryRename, _csrf: Mutation
) -> list[ManagedExpertCategory]:
    actor = await own_access(request, db, write=True)
    service.administrator(actor)
    row = await require_category(db, actor.tenant.id, category_id)
    mutable(row, body.revision)
    await unique_name(db, actor.tenant.id, body.name, row.id)
    old_name = row.name
    row.name, row.name_key = body.name, body.name.casefold()
    row.revision += 1
    await db.execute(
        update(ExpertRecord)
        .where(ExpertRecord.tenant_id == actor.tenant.id, ExpertRecord.category == row.id)
        .values(metadata_revision=ExpertRecord.metadata_revision + 1)
    )
    record(
        db,
        actor,
        "experts.category.rename",
        actor.tenant.id,
        body.name,
        {"category_id": row.id, "previous_name": old_name},
    )
    await db.flush()
    result = await listing(db, actor)
    await db.commit()
    return result


@router.post(
    "/{category_id}/move", response_model=list[ManagedExpertCategory], summary="管理员上下移动类别"
)
async def move(
    category_id: str, request: Request, db: DB, body: ExpertCategoryMove, _csrf: Mutation
) -> list[ManagedExpertCategory]:
    actor = await own_access(request, db, write=True)
    service.administrator(actor)
    row = await require_category(db, actor.tenant.id, category_id)
    mutable(row, body.revision)
    rows = [r for r in await category_rows(db, actor.tenant.id) if r.id != "uncategorized"]
    index = next(i for i, r in enumerate(rows) if r.id == category_id)
    destination = index + (-1 if body.direction == "up" else 1)
    if destination < 0 or destination >= len(rows):
        raise HTTPException(409, "已到类别列表边界，请刷新后重试")
    other = rows[destination]
    row.position, other.position = other.position, row.position
    row.revision += 1
    other.revision += 1
    record(
        db,
        actor,
        "experts.category.move",
        actor.tenant.id,
        row.name,
        {"category_id": row.id, "direction": body.direction},
    )
    await db.flush()
    result = await listing(db, actor)
    await db.commit()
    return result


@router.delete(
    "/{category_id}", response_model=Message, summary="原子迁移关联专家并删除类别，保留包和授权"
)
async def delete(
    category_id: str, request: Request, db: DB, body: ExpertCategoryDelete, _csrf: Mutation
) -> Message:
    actor = await own_access(request, db, write=True)
    service.administrator(actor)
    row = await require_category(db, actor.tenant.id, category_id)
    mutable(row, body.revision)
    if body.target_id == category_id:
        raise HTTPException(422, "请选择其他类别接收专家")
    await require_category(db, actor.tenant.id, body.target_id)
    conditions = (ExpertRecord.tenant_id == actor.tenant.id, ExpertRecord.category == category_id)
    count = await db.scalar(select(func.count()).select_from(ExpertRecord).where(*conditions)) or 0
    if count != body.count:
        raise HTTPException(409, "关联专家数量已变化，请刷新后重新确认")
    await db.execute(
        update(ExpertRecord)
        .where(*conditions)
        .values(
            category=body.target_id,
            revision=ExpertRecord.revision + 1,
            metadata_revision=ExpertRecord.metadata_revision + 1,
        )
    )
    await db.delete(row)
    record(
        db,
        actor,
        "experts.category.delete",
        actor.tenant.id,
        row.name,
        {"category_id": row.id, "target_id": body.target_id, "expert_count": str(count)},
    )
    await db.commit()
    return Message(message="类别已删除，关联专家已迁移" if count else "类别已删除")
