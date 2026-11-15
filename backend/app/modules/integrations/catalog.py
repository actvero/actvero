"""Service catalogs and versioned artifacts for external application clients."""

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func, select

from app.modules.auth.service import DB, now, provider
from app.modules.desktop.errors import fail
from app.modules.desktop_skills import service as skills
from app.modules.desktop_skills.schemas import (
    DesktopSkillDetail,
    DesktopSkillPage,
    SkillDownloadInput,
)
from app.modules.experts import desktop as experts
from app.modules.experts.connector_access import connector_endpoint
from app.modules.experts.connector_contracts import current_state_v3
from app.modules.experts.models import ExpertRecord, ExpertRelease
from app.modules.experts.schemas import ExpertDependencyRefs, PublishedSkillRef
from app.modules.integrations import service
from app.modules.integrations.actor import ApplicationActor
from app.modules.mcp import service as mcp
from app.modules.mcp.credentials import SHARED
from app.modules.mcp.models import McpConnection, McpService
from app.modules.members.service import record
from app.modules.skills.models import Skill, SkillPackage, SkillVersion
from app.modules.skills.packages import read_file
from app.modules.skills.schemas import SkillFileContent

router = APIRouter()


class ApplicationMcpService(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: str
    version: int
    endpoint: str
    configured: bool


class ApplicationMcpPage(BaseModel):
    items: list[ApplicationMcpService]
    total: int
    page: int
    page_size: Literal[20] = 20


async def touch(db: DB, actor: ApplicationActor) -> None:
    actor.key.last_used_at = now()
    await db.commit()


async def connector_ready(db: DB, connector: McpService) -> bool:
    return (
        connector.auth_mode == "none"
        or await db.get(McpConnection, (connector.id, SHARED)) is not None
    )


@router.get(
    "/mcp/services",
    response_model=ApplicationMcpPage,
    tags=["application-mcp"],
    summary="同步可用的组织 MCP 服务和网关地址",
)
async def connectors(
    request: Request,
    db: DB,
    page: int = Query(1, ge=1),
    q: str = Query("", max_length=100),
) -> ApplicationMcpPage:
    actor = await service.authorize(request, db, "mcp")
    conditions = [
        McpService.tenant_id == actor.tenant.id,
        McpService.enabled.is_(True),
        McpService.audience == "organization",
        McpService.auth_mode.in_(("none", "organization")),
    ]
    if q.strip():
        conditions.append(McpService.name.icontains(q.strip(), autoescape=True))
    total = await db.scalar(select(func.count()).select_from(McpService).where(*conditions))
    rows = await db.scalars(
        select(McpService)
        .where(*conditions)
        .order_by(McpService.name, McpService.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    root = provider(request).settings.app_url.rstrip("/")
    result = ApplicationMcpPage(
        page=page,
        total=total or 0,
        items=[
            ApplicationMcpService(
                id=row.id,
                name=row.name,
                display_name=row.display_name,
                description=row.description,
                version=row.version,
                endpoint=f"{root}/api/mcp/services/{row.id}",
                configured=await connector_ready(db, row),
            )
            for row in rows
        ],
    )
    await touch(db, actor)
    return result


@router.get(
    "/skills",
    response_model=DesktopSkillPage,
    tags=["application-skills"],
    summary="同步已发布的 Skills",
)
async def skill_catalog(
    request: Request,
    db: DB,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> DesktopSkillPage:
    actor = await service.authorize(request, db, "skills")
    query = select(Skill, SkillVersion).where(*skills.visibility(actor, q))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.execute(query.order_by(Skill.name, Skill.id).offset((page - 1) * 20).limit(20))
    result = DesktopSkillPage(
        items=[skills.view(*row) for row in rows], total=total or 0, page=page
    )
    await touch(db, actor)
    return result


@router.get(
    "/skills/{skill_id}",
    response_model=DesktopSkillDetail,
    tags=["application-skills"],
    summary="读取生效 Skill 的说明、文件清单、版本和摘要",
)
async def skill_detail(skill_id: UUID, request: Request, db: DB) -> DesktopSkillDetail:
    actor = await service.authorize(request, db, "skills")
    skill, version = await skills.current(db, actor, skill_id)
    return DesktopSkillDetail(
        **skills.view(skill, version).model_dump(),
        skill_md=version.skill_md,
        entrypoint=next(
            str(f["path"]) for f in version.files if str(f["path"]).split("/")[-1] == "SKILL.md"
        ),
        files=version.files,
    )


@router.get(
    "/skills/{skill_id}/file",
    response_model=SkillFileContent,
    tags=["application-skills"],
    summary="读取生效 Skill 的文本文件",
)
async def skill_file(
    skill_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    path: str = Query(max_length=500),
) -> SkillFileContent:
    actor = await service.authorize(request, db, "skills")
    _, version = await skills.current(db, actor, skill_id, version_id)
    package = await db.get(SkillPackage, version.id)
    if not package:
        fail(404, "skill_unavailable", "技能包不可用")
    return SkillFileContent(
        path=path, content=await run_in_threadpool(read_file, package.data, path)
    )


async def pinned_skill(
    db: DB, actor: ApplicationActor, ref: PublishedSkillRef
) -> tuple[Skill, SkillVersion]:
    skill, _ = await skills.current(db, actor, ref.skill_id)
    version = await db.get(SkillVersion, ref.version_id, populate_existing=True)
    if (
        not version
        or version.skill_id != skill.id
        or version.status not in {"published", "superseded"}
        or version.sha256 != ref.sha256
        or await db.get(SkillPackage, version.id) is None
    ):
        fail(409, "skill_version_unavailable", "专家引用的精确技能版本已不可用")
    return skill, version


@router.post(
    "/skills/{skill_id}/download",
    response_class=Response,
    tags=["application-skills"],
    summary="按版本及 SHA-256 下载 Skill ZIP",
    responses={
        200: {
            "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "X-Content-SHA256": {"schema": {"type": "string"}},
                "X-Skill-Version-ID": {"schema": {"type": "string", "format": "uuid"}},
            },
        }
    },
)
async def skill_download(
    skill_id: UUID,
    body: SkillDownloadInput,
    request: Request,
    db: DB,
) -> Response:
    actor = await service.authorize(request, db, "skills")
    if body.expert_id:
        service.require(actor, "experts")
        _, release = await experts.current(db, actor, body.expert_id)
        if release.id != body.expert_release_id:
            fail(409, "expert_release_changed", "专家发布已变化，请重新同步")
        refs = ExpertDependencyRefs.model_validate(release.dependency_refs)
        ref = next(
            (
                r
                for r in refs.skills
                if r.skill_id == skill_id
                and r.version_id == body.version_id
                and r.sha256 == body.sha256
            ),
            None,
        )
        if not ref:
            fail(404, "skill_reference_unavailable", "专家发布没有引用此技能版本")
        skill, version = await pinned_skill(db, actor, ref)
    else:
        skill, version = await skills.current(db, actor, skill_id, body.version_id)
    if version.sha256 != body.sha256:
        fail(409, "skill_version_changed", "包摘要不一致，请重新同步")
    package = await db.get(SkillPackage, version.id)
    if not package:
        fail(404, "skill_unavailable", "技能包不可用")
    record(db, actor, "skill.download", skill.id, skill.display_name, {"version": version.version})
    await touch(db, actor)
    return Response(
        package.data,
        media_type="application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="{skill.name}-{version.version}.zip"',
            "X-Content-SHA256": version.sha256,
            "X-Skill-Version-ID": str(version.id),
        },
    )


@router.get(
    "/experts",
    response_model=experts.DesktopExpertPage,
    tags=["application-experts"],
    summary="同步组织已发布的专家",
)
async def expert_catalog(
    request: Request,
    db: DB,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> experts.DesktopExpertPage:
    actor = await service.authorize(request, db, "experts")
    query = select(ExpertRecord, ExpertRelease).where(*experts.visibility(actor, q))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.execute(
        query.order_by(ExpertRelease.manifest["name"].astext, ExpertRecord.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    result = experts.DesktopExpertPage(
        items=[await experts.overview(db, *row) for row in rows], page=page, total=total or 0
    )
    await touch(db, actor)
    return result


@router.get(
    "/experts/{expert_id}",
    response_model=experts.ExpertEnvelope,
    tags=["application-experts"],
    summary="读取专家的生效发布、清单及依赖引用",
)
async def expert_detail(
    expert_id: UUID,
    request: Request,
    db: DB,
    release_id: UUID | None = None,
) -> experts.ExpertEnvelope:
    actor = await service.authorize(request, db, "experts")
    row, release = await experts.current(db, actor, expert_id)
    if release_id and release_id != release.id:
        fail(409, "expert_release_changed", "专家发布已变化，请重新同步")
    return experts.ExpertEnvelope(
        **(await experts.overview(db, row, release)).model_dump(),
        manifest=release.manifest,
        dependency_refs=release.dependency_refs,
    )


@router.post(
    "/experts/{expert_id}/resolve",
    response_model=experts.ExpertResolution,
    tags=["application-experts"],
    summary="核对专家发布及依赖的可用性，返回受发布限制的 MCP 地址",
)
async def resolve_expert(
    expert_id: UUID,
    body: experts.ExpertProof,
    request: Request,
    db: DB,
) -> experts.ExpertResolution:
    actor = await service.authorize(request, db, "experts")
    _, release = await experts.current(db, actor, expert_id)
    if release.id != body.release_id or release.sha256 != body.sha256:
        fail(409, "expert_release_changed", "专家发布或摘要已变化，请重新同步")
    refs = ExpertDependencyRefs.model_validate(release.dependency_refs)
    dependencies = []
    for kind in ("skills", "connectors"):
        for requirement in release.manifest[kind]:
            dependencies.append(
                await resolve_dependency(db, request, actor, release, refs, kind, requirement)
            )
    return experts.ExpertResolution(
        **body.model_dump(),
        checked_at=now().isoformat(),
        can_prepare=all(not item.required or item.status == "available" for item in dependencies),
        dependencies=dependencies,
    )


async def resolve_dependency(
    db: DB,
    request: Request,
    actor: ApplicationActor,
    release: ExpertRelease,
    refs: ExpertDependencyRefs,
    kind: Literal["skills", "connectors"],
    requirement: dict[str, Any],
) -> experts.ResolvedExpertDependency:
    key = requirement["key"]
    result = experts.ResolvedExpertDependency(
        kind=kind,
        key=key,
        required=requirement["required"],
        status="unavailable",
        action="contact_admin",
    )
    if kind == "skills":
        skill_ref = next((r for r in refs.skills if r.key == key), None)
        if actor.application.skills_enabled and skill_ref:
            try:
                skill, version = await pinned_skill(db, actor, skill_ref)
            except HTTPException:
                return result
            result.resource_id, result.version_id, result.sha256 = (
                skill.id,
                version.id,
                version.sha256,
            )
            result.status, result.action = "available", "none"
        return result
    ref = next((r for r in refs.connectors if r.key == key), None)
    if not actor.application.mcp_enabled or not ref:
        return result
    connector = await db.get(McpService, ref.connector_id)
    if not connector or not mcp.visible(connector, actor):
        return result
    result.resource_id = connector.id
    if not await connector_ready(db, connector):
        result.status = "connection_required"
        return result
    if ref.reference_version == 3:
        result.status, result.change_kind = await current_state_v3(
            db, connector, SHARED, ref.model_dump(mode="json")
        )
    else:
        from app.modules.experts.connector_contracts import state

        result.status = await state(db, connector, SHARED, ref.model_dump(mode="json"))
    if result.status == "available":
        result.action = "none"
        result.tools = ref.tools
        result.mcp_endpoint = connector_endpoint(
            request, connector.id, release.expert_id, release.id, key
        )
    return result
