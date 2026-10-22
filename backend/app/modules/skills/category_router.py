from fastapi import APIRouter, Request

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.skills import category_operations
from app.modules.skills.categories import (
    CategoryDelete,
    CategoryMove,
    CategoryName,
    CategoryRename,
    ManagedSkillCategory,
)

router = APIRouter(prefix="/categories")


@router.get(
    "", response_model=list[ManagedSkillCategory], summary="管理员读取动态类别与全部技能数量"
)
async def categories(request: Request, db: DB) -> list[ManagedSkillCategory]:
    actor = await own_access(request, db)
    result = await category_operations.categories(actor=actor, request=request, db=db)
    await db.commit()
    return result


@router.post("", response_model=list[ManagedSkillCategory], summary="管理员新增类别")
async def create(
    request: Request, db: DB, body: CategoryName, _csrf: Mutation
) -> list[ManagedSkillCategory]:
    actor = await own_access(request, db, write=True)
    result = await category_operations.create(actor=actor, request=request, db=db, body=body)
    await db.commit()
    return result


@router.patch(
    "/{category_id}", response_model=list[ManagedSkillCategory], summary="管理员改名，保留类别 ID"
)
async def rename(
    category_id: str, request: Request, db: DB, body: CategoryRename, _csrf: Mutation
) -> list[ManagedSkillCategory]:
    actor = await own_access(request, db, write=True)
    result = await category_operations.rename(
        actor=actor, category_id=category_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.post(
    "/{category_id}/move", response_model=list[ManagedSkillCategory], summary="管理员上下移动类别"
)
async def move(
    category_id: str, request: Request, db: DB, body: CategoryMove, _csrf: Mutation
) -> list[ManagedSkillCategory]:
    actor = await own_access(request, db, write=True)
    result = await category_operations.move(
        actor=actor, category_id=category_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.delete(
    "/{category_id}", response_model=Message, summary="原子迁移关联技能并删除类别，保留包和授权"
)
async def delete(
    category_id: str, request: Request, db: DB, body: CategoryDelete, _csrf: Mutation
) -> Message:
    actor = await own_access(request, db, write=True)
    result = await category_operations.delete(
        actor=actor, category_id=category_id, request=request, db=db, body=body
    )
    await db.commit()
    return result
