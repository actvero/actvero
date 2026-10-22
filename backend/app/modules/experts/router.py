from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.experts import operations
from app.modules.experts.categories import CategoryId
from app.modules.experts.category_router import router as category_router
from app.modules.experts.dependency_schemas import (
    DependencyCommandView,
    ExpertSkillRefresh,
)
from app.modules.experts.schemas import (
    ExpertDependencyOption,
    ExpertDependencyPage,
    ExpertPage,
    ExpertPublish,
    ExpertRevision,
    ExpertSave,
    ExpertScope,
    ExpertSkillImpactView,
    ExpertUpdate,
    ExpertView,
)

router = APIRouter(prefix="/api/v1/experts", tags=["experts"])
router.include_router(category_router)


@router.get(
    "/dependency-commands/{request_id}",
    response_model=DependencyCommandView,
    summary="本人原更新命令回执；无回执不代表请求不会稍后完成",
)
async def dependency_receipt(request_id: UUID, request: Request, db: DB) -> DependencyCommandView:
    actor = await own_access(request, db)
    result = await operations.dependency_receipt(
        actor=actor, request_id=request_id, request=request, db=db
    )
    await db.commit()
    return result


@router.get(
    "/skill-impact",
    response_model=ExpertSkillImpactView,
    summary="分页搜索草稿和当前发布的技能引用；精确选择更新草稿",
)
async def skill_impact(
    request: Request,
    db: DB,
    skill_id: UUID,
    target_version_id: UUID | None = None,
    source_version_id: UUID | None = None,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> ExpertSkillImpactView:
    actor = await own_access(request, db)
    result = await operations.skill_impact(
        actor=actor,
        request=request,
        db=db,
        skill_id=skill_id,
        target_version_id=target_version_id,
        source_version_id=source_version_id,
        q=q,
        page=page,
    )
    await db.commit()
    return result


@router.get("", response_model=ExpertPage, summary="管理员查询专家草稿与发布状态")
async def listing(
    request: Request,
    db: DB,
    q: str = Query("", max_length=100),
    category: CategoryId | None = None,
    status: Literal["published", "unpublished"] | None = None,
    page: int = Query(1, ge=1),
) -> ExpertPage:
    actor = await own_access(request, db)
    result = await operations.listing(
        actor=actor, request=request, db=db, q=q, category=category, status=status, page=page
    )
    await db.commit()
    return result


@router.get(
    "/dependencies", response_model=ExpertDependencyPage, summary="管理员选择真实已登记能力"
)
async def options(
    request: Request,
    db: DB,
    kind: Literal["skills", "connectors"],
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> ExpertDependencyPage:
    actor = await own_access(request, db)
    result = await operations.options(
        actor=actor, request=request, db=db, kind=kind, q=q, page=page
    )
    await db.commit()
    return result


@router.get("/dependencies/{kind}/{resource_id}", response_model=ExpertDependencyOption)
async def dependency_detail(
    kind: Literal["skills", "connectors"],
    resource_id: UUID,
    request: Request,
    db: DB,
    version_id: UUID | None = None,
) -> ExpertDependencyOption:
    actor = await own_access(request, db)
    result = await operations.dependency_detail(
        actor=actor,
        kind=kind,
        resource_id=resource_id,
        request=request,
        db=db,
        version_id=version_id,
    )
    await db.commit()
    return result


@router.post("", response_model=ExpertView, summary="管理员保存专家草稿，默认仅管理员")
async def create(request: Request, db: DB, body: ExpertSave, _csrf: Mutation) -> ExpertView:
    actor = await own_access(request, db, write=True)
    result = await operations.create(actor=actor, request=request, db=db, body=body)
    await db.commit()
    return result


@router.get("/{expert_id}", response_model=ExpertView)
async def detail(expert_id: UUID, request: Request, db: DB) -> ExpertView:
    actor = await own_access(request, db)
    result = await operations.detail(actor=actor, expert_id=expert_id, request=request, db=db)
    await db.commit()
    return result


@router.delete(
    "/{expert_id}",
    response_model=Message,
    summary="删除专家及全部发布版本，保留操作记录和关联资源",
)
async def delete_expert(
    expert_id: UUID, request: Request, db: DB, body: ExpertRevision, _csrf: Mutation
) -> Message:
    actor = await own_access(request, db, write=True)
    result = await operations.delete_expert(
        actor=actor, expert_id=expert_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.post(
    "/{expert_id}/refresh-skills",
    response_model=ExpertView,
    summary="把当前生效技能版本载入草稿，保留发布版本",
)
async def refresh_skills(
    expert_id: UUID, request: Request, db: DB, body: ExpertSkillRefresh, _csrf: Mutation
) -> ExpertView:
    actor = await own_access(request, db, write=True)
    result = await operations.refresh_skills(
        actor=actor, expert_id=expert_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.put("/{expert_id}", response_model=ExpertView, summary="修改草稿，当前发布保持不变")
async def update(
    expert_id: UUID, request: Request, db: DB, body: ExpertUpdate, _csrf: Mutation
) -> ExpertView:
    actor = await own_access(request, db, write=True)
    result = await operations.update(
        actor=actor, expert_id=expert_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.put("/{expert_id}/scope", response_model=ExpertView, summary="修改全部版本共用的成员范围")
async def update_scope(
    expert_id: UUID, request: Request, db: DB, body: ExpertScope, _csrf: Mutation
) -> ExpertView:
    actor = await own_access(request, db, write=True)
    result = await operations.update_scope(
        actor=actor, expert_id=expert_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.post(
    "/{expert_id}/publish", response_model=ExpertView, summary="创建不可变发布，替换当前发布"
)
async def publish(
    expert_id: UUID, request: Request, db: DB, body: ExpertPublish, _csrf: Mutation
) -> ExpertView:
    actor = await own_access(request, db, write=True)
    result = await operations.publish(
        actor=actor, expert_id=expert_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.post("/{expert_id}/withdraw", response_model=ExpertView, summary="下架专家，保留版本与草稿")
async def withdraw(
    expert_id: UUID, request: Request, db: DB, body: ExpertRevision, _csrf: Mutation
) -> ExpertView:
    actor = await own_access(request, db, write=True)
    result = await operations.withdraw(
        actor=actor, expert_id=expert_id, request=request, db=db, body=body
    )
    await db.commit()
    return result
