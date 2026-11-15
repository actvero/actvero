"""Sources and draft writes for independent organization applications."""

from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.modules.auth.service import DB, now
from app.modules.desktop.errors import fail
from app.modules.experts import operations as expert_operations
from app.modules.experts.models import ExpertRecord, ExpertRelease
from app.modules.experts.schemas import ExpertContent, ExpertSave
from app.modules.experts.service import check
from app.modules.integrations import service
from app.modules.integrations.actor import ApplicationActor
from app.modules.integrations.models import IntegrationResourceSource
from app.modules.integrations.write_schemas import (
    ExpertResourceWrite,
    McpResourceWrite,
    PushedSkillVersion,
    ResourceKind,
    ResourceWriteView,
    Revision,
    SourceId,
)
from app.modules.mcp import operations as mcp_operations
from app.modules.mcp.models import McpService
from app.modules.mcp.schemas import McpServiceUpdate
from app.modules.skills import operations as skill_operations
from app.modules.skills.models import Skill, SkillVersion
from app.modules.skills.packages import MAX_PACKAGE, inspect_package
from app.modules.skills.schemas import SkillReleaseInput, SkillVersionNumber, SkillVersionView
from app.modules.tenants.models import Tenant

router = APIRouter(prefix="/write", tags=["application-resource-writes"])
WRITE_SCOPE: dict[ResourceKind, service.Capability] = {
    "mcp": "mcp_write",
    "skills": "skills_write",
    "experts": "experts_write",
}


async def access(
    request: Request, db: DB, kind: ResourceKind, *, lock: bool = False
) -> ApplicationActor:
    actor = await service.authorize(request, db, WRITE_SCOPE[kind])
    if lock:
        # The Web and management writers use the same organization lock.
        await db.scalar(select(Tenant.id).where(Tenant.id == actor.tenant.id).with_for_update())
        actor = await service.authorize(request, db, WRITE_SCOPE[kind])
    return actor


async def source_for(
    db: DB, actor: ApplicationActor, kind: ResourceKind, source_id: str
) -> IntegrationResourceSource | None:
    return await db.get(IntegrationResourceSource, (actor.application.id, kind, source_id))


async def target[T: (McpService, Skill, ExpertRecord)](
    db: DB, actor: ApplicationActor, source: IntegrationResourceSource, model: type[T]
) -> T:
    row = await db.get(model, source.resource_id)
    if row is None or row.tenant_id != actor.tenant.id:
        fail(404, "source_resource_removed", "此来源对应的资源已被移除")
    return row


def ensure_revision(expected: int, revision: int) -> None:
    if expected != revision:
        fail(409, "source_revision_conflict", "资源修订号已变化，请读取来源状态后重试")


def fingerprint(body: BaseModel) -> str:
    return sha256(body.model_dump_json(exclude={"revision"}).encode()).hexdigest()


def save_source(
    db: DB,
    actor: ApplicationActor,
    kind: ResourceKind,
    source_id: str,
    source: IntegrationResourceSource | None,
    resource_id: UUID,
    digest: str,
) -> None:
    if source is None:
        db.add(
            IntegrationResourceSource(
                application_id=actor.application.id,
                kind=kind,
                source_id=source_id,
                resource_id=resource_id,
                fingerprint=digest,
            )
        )
    else:
        source.fingerprint = digest


def mcp_view(source_id: str, row: McpService) -> ResourceWriteView:
    return ResourceWriteView(
        kind="mcp",
        source_id=source_id,
        resource_id=row.id,
        revision=row.version,
        status="enabled" if row.enabled else "disabled",
    )


def skill_view(source_id: str, row: Skill, version: SkillVersion) -> ResourceWriteView:
    return ResourceWriteView(
        kind="skills",
        source_id=source_id,
        resource_id=row.id,
        revision=row.revision,
        status=SkillVersionView.model_validate(version).status,
        current_release_id=row.default_version_id,
        skill_version=PushedSkillVersion(
            id=version.id, version=version.version, sha256=version.sha256
        ),
    )


async def expert_view(db: DB, source_id: str, row: ExpertRecord) -> ResourceWriteView:
    release = (
        await db.get(ExpertRelease, row.current_release_id) if row.current_release_id else None
    )
    return ResourceWriteView(
        kind="experts",
        source_id=source_id,
        resource_id=row.id,
        revision=row.revision,
        status="published" if release and release.content == row.draft else "draft",
        current_release_id=row.current_release_id,
        dependency_check=await check(db, row, ExpertContent.model_validate(row.draft)),
    )


@router.get("/{kind}/{source_id}", summary="读取本应用推送资源的修订和审核状态")
async def status(
    kind: ResourceKind, source_id: SourceId, request: Request, db: DB
) -> ResourceWriteView:
    actor = await access(request, db, kind)
    source = await source_for(db, actor, kind, source_id)
    if not source:
        fail(404, "source_not_found", "此应用尚未推送该来源")
    if kind == "mcp":
        result = mcp_view(source_id, await target(db, actor, source, McpService))
    elif kind == "skills":
        skill = await target(db, actor, source, Skill)
        version = await db.scalar(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill.id)
            .order_by(SkillVersion.created_at.desc(), SkillVersion.id)
            .limit(1)
        )
        if not version:
            fail(404, "source_resource_removed", "此技能已无可用版本")
        result = skill_view(source_id, skill, version)
    else:
        result = await expert_view(db, source_id, await target(db, actor, source, ExpertRecord))
    actor.key.last_used_at = now()
    await db.commit()
    return result


@router.put("/mcp/{source_id}", summary="推送 MCP 服务配置")
async def push_mcp(
    source_id: SourceId, body: McpResourceWrite, request: Request, db: DB
) -> ResourceWriteView:
    actor = await access(request, db, "mcp", lock=True)
    source = await source_for(db, actor, "mcp", source_id)
    row = await target(db, actor, source, McpService) if source else None
    digest = fingerprint(body)
    if source is None or source.fingerprint != digest:
        ensure_revision(body.revision, row.version if row else 0)
        config = body.service_input()
        if row:
            updates = McpServiceUpdate(
                **config.model_dump(
                    exclude={
                        "audience",
                        "member_ids",
                        "department_grants",
                        "enabled",
                        "connection_options",
                    }
                ),
                audience=row.audience,
                member_ids=row.member_ids,
                enabled=row.enabled,
                connection_options=row.connection_options,
                version=row.version,
            )
            await mcp_operations.save_service(actor, request, db, row, updates)
        else:
            row = await mcp_operations.insert_service(actor, request, db, config)
        save_source(db, actor, "mcp", source_id, source, row.id, digest)
    assert row is not None
    actor.key.last_used_at = now()
    await db.commit()
    return mcp_view(source_id, row)


@router.put(
    "/skills/{source_id}",
    summary="推送完整技能 ZIP 并追加版本草稿",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/zip": {"schema": {"type": "string", "format": "binary"}},
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
            },
        }
    },
)
async def push_skill(
    source_id: SourceId,
    version: Annotated[SkillVersionNumber, Query()],
    revision: Annotated[Revision, Query()],
    request: Request,
    db: DB,
) -> ResourceWriteView:
    await access(request, db, "skills")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() not in {
        "application/zip",
        "application/octet-stream",
    }:
        fail(415, "skill_zip_required", "请以二进制请求体上传技能 ZIP")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_PACKAGE:
            fail(413, "skill_zip_too_large", "技能包不能超过 20 MiB")
    raw = bytes(data)
    package = await run_in_threadpool(inspect_package, raw)
    actor = await access(request, db, "skills", lock=True)
    source = await source_for(db, actor, "skills", source_id)
    skill = await target(db, actor, source, Skill) if source else None
    existing = (
        await db.scalar(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill.id, SkillVersion.sha256 == package.sha256)
            .order_by(SkillVersion.created_at, SkillVersion.id)
            .limit(1)
        )
        if skill
        else None
    )
    if existing is None:
        ensure_revision(revision, skill.revision if skill else 0)
        body = SkillReleaseInput(
            audience="administrators",
            display_name=package.name,
            description=package.description,
            version=version,
            revision=revision,
        )
        skill, existing = await skill_operations.save_package(
            actor, db, body, package, raw, skill, []
        )
        save_source(db, actor, "skills", source_id, source, skill.id, package.sha256)
    assert skill is not None
    actor.key.last_used_at = now()
    await db.commit()
    return skill_view(source_id, skill, existing)


@router.put("/experts/{source_id}", summary="推送专家草稿并校验精确依赖")
async def push_expert(
    source_id: SourceId, body: ExpertResourceWrite, request: Request, db: DB
) -> ResourceWriteView:
    actor = await access(request, db, "experts", lock=True)
    source = await source_for(db, actor, "experts", source_id)
    row = await target(db, actor, source, ExpertRecord) if source else None
    digest = fingerprint(body)
    if source is None or source.fingerprint != digest:
        ensure_revision(body.revision, row.revision if row else 0)
        draft = ExpertSave(content=body.content, category=row.category if row else "uncategorized")
        row = await expert_operations.save_draft(actor, db, draft, row)
        save_source(db, actor, "experts", source_id, source, row.id, digest)
    assert row is not None
    result = await expert_view(db, source_id, row)
    actor.key.last_used_at = now()
    await db.commit()
    return result
