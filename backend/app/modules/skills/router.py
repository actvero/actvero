from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.skills import operations
from app.modules.skills.categories import CategoryId
from app.modules.skills.category_router import router as category_router
from app.modules.skills.schemas import (
    Audience,
    SkillAction,
    SkillDistributionPage,
    SkillFileContent,
    SkillIconOption,
    SkillImport,
    SkillOverview,
    SkillPage,
    SkillPreview,
    SkillUpdate,
    SkillView,
)

router = APIRouter(prefix="/api/v1/skills", tags=["skills"])


router.include_router(category_router)


@router.get("/icon-catalog", response_model=list[SkillIconOption], summary="管理员选择技能图标")
async def icon_catalog(request: Request, db: DB) -> list[SkillIconOption]:
    actor = await own_access(request, db)
    result = await operations.icon_catalog(actor=actor, request=request, db=db)
    await db.commit()
    return result


@router.post("/preview", response_model=SkillPreview, summary="校验单个 ZIP，不保存或执行")
async def preview(request: Request, db: DB, _csrf: Mutation) -> SkillPreview:
    actor = await own_access(request, db)
    result = await operations.preview(actor=actor, request=request, db=db)
    await db.commit()
    return result


@router.post("/import", response_model=SkillView, summary="管理员上传技能或不可变的新版本草稿")
async def import_skill(request: Request, db: DB, body: SkillImport, _csrf: Mutation) -> SkillView:
    actor = await own_access(request, db, write=True)
    result = await operations.import_skill(actor=actor, request=request, db=db, body=body)
    await db.commit()
    return result


@router.get(
    "", response_model=SkillPage, summary="当前组织可见技能；普通成员仅可见获授权的已发布版本"
)
async def list_skills(
    request: Request,
    db: DB,
    audience: Audience | None = None,
    category: CategoryId | None = None,
    status: Literal["published", "unpublished"] | None = None,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
) -> SkillPage:
    actor = await own_access(request, db)
    result = await operations.list_skills(
        actor=actor,
        request=request,
        db=db,
        audience=audience,
        category=category,
        status=status,
        q=q,
        page=page,
    )
    await db.commit()
    return result


@router.get(
    "/distributions",
    response_model=SkillDistributionPage,
    summary="管理员查看技能包发放记录（不等于安装成功）",
)
async def distributions(
    request: Request, db: DB, skill_id: UUID | None = None, page: int = Query(default=1, ge=1)
) -> SkillDistributionPage:
    actor = await own_access(request, db)
    result = await operations.distributions(
        actor=actor, request=request, db=db, skill_id=skill_id, page=page
    )
    await db.commit()
    return result


@router.get("/{skill_id}", response_model=SkillView)
async def detail(skill_id: UUID, request: Request, db: DB) -> SkillView:
    actor = await own_access(request, db)
    result = await operations.detail(actor=actor, skill_id=skill_id, request=request, db=db)
    await db.commit()
    return result


@router.put(
    "/{skill_id}",
    response_model=SkillView,
    summary="管理员修改技能展示资料及所有版本共用的使用范围",
)
async def update(
    skill_id: UUID, request: Request, db: DB, body: SkillUpdate, _csrf: Mutation
) -> SkillView:
    actor = await own_access(request, db, write=True)
    result = await operations.update(
        actor=actor, skill_id=skill_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.post(
    "/{skill_id}/versions/{version_id}/actions",
    response_model=SkillView,
    summary="发布唯一推荐版本（保留获准历史引用），或停止指定发布版本",
)
async def action(
    skill_id: UUID, version_id: UUID, request: Request, db: DB, body: SkillAction, _csrf: Mutation
) -> SkillView:
    actor = await own_access(request, db, write=True)
    result = await operations.action(
        actor=actor, skill_id=skill_id, version_id=version_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.delete(
    "/{skill_id}/versions/{version_id}", response_model=Message, summary="仅删除从未发布的草稿"
)
async def delete_draft(
    skill_id: UUID, version_id: UUID, request: Request, db: DB, _csrf: Mutation, revision: int
) -> Message:
    actor = await own_access(request, db, write=True)
    result = await operations.delete_draft(
        actor=actor,
        skill_id=skill_id,
        version_id=version_id,
        request=request,
        db=db,
        revision=revision,
    )
    await db.commit()
    return result


@router.get("/{skill_id}/versions/{version_id}/overview", response_model=SkillOverview)
async def overview(skill_id: UUID, version_id: UUID, request: Request, db: DB) -> SkillOverview:
    actor = await own_access(request, db)
    result = await operations.overview(
        actor=actor, skill_id=skill_id, version_id=version_id, request=request, db=db
    )
    await db.commit()
    return result


@router.get("/{skill_id}/versions/{version_id}/file", response_model=SkillFileContent)
async def file_content(
    skill_id: UUID, version_id: UUID, request: Request, db: DB, path: str = Query(max_length=500)
) -> SkillFileContent:
    actor = await own_access(request, db)
    result = await operations.file_content(
        actor=actor, skill_id=skill_id, version_id=version_id, request=request, db=db, path=path
    )
    await db.commit()
    return result


@router.post(
    "/{skill_id}/versions/{version_id}/download",
    response_class=Response,
    summary="重新校验授权并发放原始 ZIP；记录发放，不宣称安装完成",
)
async def download(
    skill_id: UUID, version_id: UUID, request: Request, db: DB, _csrf: Mutation
) -> Response:
    actor = await own_access(request, db, write=True)
    data, filename, checksum = await operations.download_package(
        actor, request, db, skill_id, version_id
    )
    await db.commit()
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-SHA256": checksum,
        },
    )
