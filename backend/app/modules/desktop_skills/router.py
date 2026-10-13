from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPBearer
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from app.modules.auth.service import DB
from app.modules.desktop import adoptions
from app.modules.desktop.errors import DesktopError, fail
from app.modules.desktop.resources import SKILLS_CATALOG, authorize
from app.modules.desktop.schemas import DesktopErrorResponse
from app.modules.desktop_skills import service
from app.modules.desktop_skills.schemas import (
    DesktopSkillCategory,
    DesktopSkillDetail,
    DesktopSkillPage,
    DesktopSkillVersion,
    SkillAdoptInput,
    SkillDownloadInput,
    SkillUpdatesInput,
    SkillUpdateState,
    SkillUpdatesView,
)
from app.modules.skills.categories import CategoryId, category_rows, category_view, require_category
from app.modules.skills.models import Skill, SkillDistribution, SkillPackage, SkillVersion
from app.modules.skills.packages import read_file
from app.modules.skills.schemas import SkillFileContent

bearer = HTTPBearer(
    scheme_name="SkillsResource",
    auto_error=False,
    description="由 /api/v1/desktop/resource-tokens 申请 skills:catalog；拒绝 Cookie/Origin。",
)
RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": DesktopErrorResponse, "description": description}
    for status, description in {
        401: "资源令牌过期、设备失效或使用了错误凭据；见 error.code。",
        403: "资源范围不符、成员/组织不可用。",
        404: "技能或文件不可用，不区分不存在与无权限。",
        409: "生效版本或摘要已变化，刷新详情并重新确认。",
        422: "请求参数无效或文件不能文本预览。",
        503: "身份服务暂不可用；保留登录，稍后重试。",
    }.items()
}
router = APIRouter(
    prefix="/api/v1/desktop/skills",
    tags=["desktop-skills"],
    dependencies=[Depends(bearer)],
    responses=RESPONSES,
)


@router.get("", response_model=DesktopSkillPage, summary="搜索当前成员获准的生效技能")
async def catalog(
    request: Request,
    db: DB,
    q: str = Query("", max_length=100),
    category: CategoryId | None = None,
    page: int = Query(1, ge=1),
) -> DesktopSkillPage:
    actor = await authorize(request, db, SKILLS_CATALOG)
    if category:
        await require_category(db, actor.tenant.id, category)
    conditions = [*service.visibility(actor, q), *service.category_condition(category)]
    total = await db.scalar(
        select(func.count()).select_from(Skill, SkillVersion).where(*conditions)
    )
    rows = (
        await db.execute(
            select(Skill, SkillVersion)
            .where(*conditions)
            .order_by(SkillVersion.published_at.desc(), Skill.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    return DesktopSkillPage(
        items=[service.view(s, v) for s, v in rows], total=total or 0, page=page
    )


@router.get(
    "/categories", response_model=list[DesktopSkillCategory], summary="类别与授权后的技能数量"
)
async def categories(
    request: Request, db: DB, q: str = Query("", max_length=100)
) -> list[DesktopSkillCategory]:
    actor = await authorize(request, db, SKILLS_CATALOG)
    counts = {
        key: count
        for key, count in (
            (
                await db.execute(
                    select(Skill.category, func.count())
                    .select_from(Skill, SkillVersion)
                    .where(*service.visibility(actor, q))
                    .group_by(Skill.category)
                )
            ).all()
        )
    }
    return [
        DesktopSkillCategory(**category_view(row).model_dump(), count=counts.get(row.id, 0))
        for row in await category_rows(db, actor.tenant.id)
    ]


@router.post(
    "/check-updates",
    response_model=SkillUpdatesView,
    summary="检查采用版是否可继续使用及是否有新版，不静默更新",
)
async def updates(request: Request, db: DB, body: SkillUpdatesInput) -> SkillUpdatesView:
    actor = await authorize(request, db, SKILLS_CATALOG)
    rows = (
        await db.execute(
            select(Skill, SkillVersion).where(
                *service.visibility(actor), Skill.id.in_([item.skill_id for item in body.items])
            )
        )
    ).all()
    available = {skill.id: service.view(skill, version) for skill, version in rows}
    items = []
    for installed in body.items:
        skill = available.get(installed.skill_id)
        state = SkillUpdateState(skill_id=installed.skill_id, status="unavailable")
        if skill:
            state.skill = skill
            state.status = (
                "current"
                if (
                    installed.version_id == skill.current_version.id
                    and installed.sha256 == skill.current_version.sha256
                )
                else "update_available"
            )
        if body.access_version == 2:
            state.adopted_usable = False
            state.adopted_state = "unavailable"
            state.update_available = bool(
                skill
                and (
                    installed.version_id != skill.current_version.id
                    or installed.sha256 != skill.current_version.sha256
                )
            )
            try:
                _, chosen = await service.exact(
                    db,
                    actor,
                    installed.skill_id,
                    installed.version_id,
                    access_version=2,
                    sha256=installed.sha256,
                    expert_id=installed.expert_id,
                    expert_release_id=installed.expert_release_id,
                )
                state.adopted_usable = True
                state.adopted_state = "current" if chosen.status == "published" else "superseded"
            except DesktopError as exc:
                if exc.status_code not in {404, 409}:
                    raise
        items.append(state)
    return SkillUpdatesView(items=items)


@router.get(
    "/{skill_id}",
    response_model=DesktopSkillDetail,
    response_model_exclude_none=True,
    summary="当前或获准的精确历史技能详情、说明和文件清单",
)
async def detail(
    skill_id: UUID,
    request: Request,
    db: DB,
    version_id: UUID | None = None,
    access_version: int = Query(1, ge=1, le=2),
    expert_id: UUID | None = None,
    expert_release_id: UUID | None = None,
) -> DesktopSkillDetail:
    actor = await authorize(request, db, SKILLS_CATALOG)
    skill, recommended = await service.current(db, actor, skill_id)
    _, version = await service.exact(
        db,
        actor,
        skill_id,
        version_id or recommended.id,
        access_version=access_version,
        expert_id=expert_id,
        expert_release_id=expert_release_id,
    )
    entrypoint = next(
        str(f["path"]) for f in version.files if str(f["path"]).split("/")[-1] == "SKILL.md"
    )
    return DesktopSkillDetail(
        **service.view(skill, version).model_dump(),
        recommended_version=DesktopSkillVersion.model_validate(recommended)
        if access_version == 2
        else None,
        version_state=("current" if version.status == "published" else "superseded")
        if access_version == 2
        else None,
        update_available=recommended.id != version.id if access_version == 2 else None,
        skill_md=version.skill_md,
        entrypoint=entrypoint,
        files=version.files,
    )


@router.get(
    "/{skill_id}/file", response_model=SkillFileContent, summary="按详情版本 ID 预览包内文本文件"
)
async def file_content(
    skill_id: UUID,
    request: Request,
    db: DB,
    version_id: UUID,
    path: str = Query(max_length=500),
    access_version: int = Query(1, ge=1, le=2),
    expert_id: UUID | None = None,
    expert_release_id: UUID | None = None,
) -> SkillFileContent:
    actor = await authorize(request, db, SKILLS_CATALOG)
    _, version = await service.exact(
        db,
        actor,
        skill_id,
        version_id,
        access_version=access_version,
        expert_id=expert_id,
        expert_release_id=expert_release_id,
    )
    package = await db.get(SkillPackage, version.id)
    if package is None:
        fail(404, "skill_unavailable", "技能包不可用")
    try:
        content = await run_in_threadpool(read_file, package.data, path)
    except HTTPException as exc:
        fail(
            exc.status_code,
            "file_unavailable" if exc.status_code == 404 else "file_not_previewable",
            "文件不可用" if exc.status_code == 404 else "此文件不支持文本预览，请下载技能包查看",
        )
    return SkillFileContent(path=path, content=content)


@router.post(
    "/{skill_id}/download",
    response_class=Response,
    summary="确认版本与摘要后发放生效 ZIP，记录桌面来源",
    responses={
        200: {
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "X-Content-SHA256": {"schema": {"type": "string"}},
                "X-Skill-Version-ID": {"schema": {"type": "string", "format": "uuid"}},
                "Content-Disposition": {"schema": {"type": "string"}},
            },
        }
    },
)
async def download(skill_id: UUID, request: Request, db: DB, body: SkillDownloadInput) -> Response:
    actor = await authorize(request, db, SKILLS_CATALOG, write=True)
    skill, version = await service.exact(
        db,
        actor,
        skill_id,
        body.version_id,
        access_version=body.access_version,
        sha256=body.sha256,
        expert_id=body.expert_id,
        expert_release_id=body.expert_release_id,
    )
    if version.sha256 != body.sha256:
        fail(409, "skill_version_changed", "包摘要不一致，请刷新详情后重新确认")
    package = await db.get(SkillPackage, version.id)
    if package is None:
        fail(404, "skill_unavailable", "技能包不可用")
    db.add(
        SkillDistribution(
            tenant_id=actor.tenant.id,
            skill_id=skill.id,
            skill_name=skill.display_name,
            version=version.version,
            actor_id=actor.user.id,
            actor_name=actor.user.name,
            source="desktop",
            device_session_id=actor.device.id,
            client_version=actor.device.app_version,
        )
    )
    data = package.data
    await db.commit()
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{skill.name}-{version.version}.zip"',
            "X-Content-SHA256": version.sha256,
            "X-Skill-Version-ID": str(version.id),
        },
    )


@router.post(
    "/{skill_id}/adopt",
    response_model=adoptions.AdoptionView,
    summary="显式选择精确版本；幂等证明不代表已安装或授予资源权限",
)
async def adopt(
    skill_id: UUID, request: Request, db: DB, body: SkillAdoptInput
) -> adoptions.AdoptionView:
    actor = await authorize(request, db, SKILLS_CATALOG, write=True)
    skill, version = await service.exact(
        db,
        actor,
        skill_id,
        body.version_id,
        access_version=2,
        sha256=body.sha256,
        expert_id=body.expert_id,
        expert_release_id=body.expert_release_id,
    )
    result = await adoptions.record(
        db,
        actor,
        "skills",
        skill.id,
        version.id,
        version.sha256,
        body.request_id,
        body.expert_id,
        body.expert_release_id,
    )
    await db.commit()
    return result
