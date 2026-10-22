"""Resource operations shared by Web and organization-scoped management routes.

Authentication and the final transaction commit belong to the caller.
"""

from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Query, Request
from sqlalchemy import delete, func, or_, select

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.experts import dependency_updates, service
from app.modules.experts.categories import CategoryId, require_category
from app.modules.experts.dependencies import connector_option, skill_option
from app.modules.experts.dependency_schemas import (
    DependencyCommandView,
    ExactSkillChange,
    ExpertDraftSelection,
    ExpertSkillRefresh,
)
from app.modules.experts.models import ExpertRecord, ExpertRelease
from app.modules.experts.schemas import (
    ExpertContent,
    ExpertDependencyOption,
    ExpertDependencyPage,
    ExpertPage,
    ExpertPublish,
    ExpertRevision,
    ExpertSave,
    ExpertScope,
    ExpertSkillImpact,
    ExpertSkillImpactView,
    ExpertUpdate,
    ExpertView,
)
from app.modules.mcp.models import McpService
from app.modules.members.service import BusinessActor, record
from app.modules.skills.icons import uploaded_image
from app.modules.skills.models import Skill, SkillVersion
from app.modules.skills.service import scope


async def dependency_receipt(
    actor: BusinessActor, request_id: UUID, request: Request, db: DB
) -> DependencyCommandView:
    service.administrator(actor)
    row = await dependency_updates.receipt(db, actor, request_id)
    if row is None:
        raise HTTPException(404, "尚无此更新回执")
    return dependency_updates.view(row)


async def skill_impact(
    actor: BusinessActor,
    request: Request,
    db: DB,
    skill_id: UUID,
    target_version_id: UUID | None = None,
    source_version_id: UUID | None = None,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> ExpertSkillImpactView:
    service.administrator(actor)
    skill = await db.get(Skill, skill_id)
    if not skill or skill.tenant_id != actor.tenant.id:
        raise HTTPException(404, "技能不存在")
    target = await db.get(SkillVersion, target_version_id) if target_version_id else None
    if target_version_id and (not target or target.skill_id != skill.id):
        raise HTTPException(422, "目标版本无效")
    source = await db.get(SkillVersion, source_version_id) if source_version_id else None
    if source_version_id and (not source or source.skill_id != skill.id):
        raise HTTPException(422, "来源版本无效")
    match = {"skill_id": str(skill.id)}
    if source_version_id:
        match["version_id"] = str(source_version_id)
    draft_match = ExpertRecord.draft["skills"].contains([match])
    published_match = ExpertRelease.dependency_refs["skills"].contains([match])
    conditions = [ExpertRecord.tenant_id == actor.tenant.id, or_(draft_match, published_match)]
    if q.strip():
        conditions.append(ExpertRecord.name.icontains(q.strip(), autoescape=True))
    query = (
        select(ExpertRecord, ExpertRelease)
        .outerjoin(
            ExpertRelease,
            (ExpertRelease.id == ExpertRecord.current_release_id)
            & (ExpertRelease.expert_id == ExpertRecord.id),
        )
        .where(*conditions)
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.execute(query.order_by(ExpertRecord.id).offset((page - 1) * 20).limit(20))
    ).all()
    ids = {
        UUID(r["version_id"])
        for (expert, release) in rows
        for r in expert.draft.get("skills", [])
        + (release.dependency_refs["skills"] if release else [])
        if r["skill_id"] == str(skill.id)
    }
    versions = {
        str(v.id): v.version
        for v in await db.scalars(
            select(SkillVersion).where(SkillVersion.id.in_(ids), SkillVersion.skill_id == skill.id)
        )
    }
    items = []
    for expert, release in rows:
        refs = [
            r
            for r in expert.draft.get("skills", [])
            if r["skill_id"] == str(skill.id)
            and (not source_version_id or r["version_id"] == str(source_version_id))
        ]
        published = (
            [
                r
                for r in release.dependency_refs["skills"]
                if r["skill_id"] == str(skill.id)
                and (not source_version_id or r["version_id"] == str(source_version_id))
            ]
            if release
            else []
        )
        changes = [
            ExactSkillChange(
                key=r["key"],
                from_version_id=r["version_id"],
                from_sha256=r["sha256"],
                to_version_id=target.id,
                to_sha256=target.sha256,
            )
            for r in refs
            if target and (r["version_id"] != str(target.id) or r["sha256"] != target.sha256)
        ]
        items.append(
            ExpertSkillImpact(
                id=expert.id,
                name=expert.name,
                version=release.version if release else "未发布",
                revision=expert.revision,
                current_release_id=expert.current_release_id,
                draft_changes=changes,
                draft_versions=[versions.get(r["version_id"], "不可用") for r in refs],
                published_versions=[versions.get(r["version_id"], "不可用") for r in published],
            )
        )
    return ExpertSkillImpactView(items=items, total=total or 0, page=page)


async def listing(
    actor: BusinessActor,
    request: Request,
    db: DB,
    q: str = Query("", max_length=100),
    category: CategoryId | None = None,
    status: Literal["published", "unpublished"] | None = None,
    page: int = Query(1, ge=1),
) -> ExpertPage:
    service.administrator(actor)
    conditions = [ExpertRecord.tenant_id == actor.tenant.id]
    if category:
        await require_category(db, actor.tenant.id, category)
        conditions.append(ExpertRecord.category == category)
    if q.strip():
        conditions.append(
            or_(
                ExpertRecord.name.icontains(q.strip(), autoescape=True),
                ExpertRecord.description.icontains(q.strip(), autoescape=True),
            )
        )
    if status:
        conditions.append(
            ExpertRecord.current_release_id.is_not(None)
            if status == "published"
            else ExpertRecord.current_release_id.is_(None)
        )
    total = await db.scalar(select(func.count()).select_from(ExpertRecord).where(*conditions))
    rows = await db.scalars(
        select(ExpertRecord)
        .where(*conditions)
        .order_by(ExpertRecord.created_at.desc(), ExpertRecord.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    return ExpertPage(
        items=[await service.summary(db, r) for r in rows], total=total or 0, page=page
    )


async def options(
    actor: BusinessActor,
    request: Request,
    db: DB,
    kind: Literal["skills", "connectors"],
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> ExpertDependencyPage:
    service.administrator(actor)
    if kind == "skills":
        conditions = [
            Skill.tenant_id == actor.tenant.id,
            SkillVersion.skill_id == Skill.id,
            SkillVersion.id == Skill.default_version_id,
            SkillVersion.status == "published",
        ]
        if q.strip():
            conditions.append(
                or_(
                    Skill.display_name.icontains(q.strip(), autoescape=True),
                    Skill.description.icontains(q.strip(), autoescape=True),
                )
            )
        total = await db.scalar(
            select(func.count()).select_from(Skill, SkillVersion).where(*conditions)
        )
        rows = (
            await db.execute(
                select(Skill, SkillVersion)
                .where(*conditions)
                .order_by(Skill.display_name, Skill.id)
                .offset((page - 1) * 20)
                .limit(20)
            )
        ).all()
        items = [skill_option(s, v) for (s, v) in rows]
    else:
        conditions = [McpService.tenant_id == actor.tenant.id]
        if q.strip():
            conditions.append(
                or_(
                    McpService.name.icontains(q.strip(), autoescape=True),
                    McpService.display_name.icontains(q.strip(), autoescape=True),
                )
            )
        total = await db.scalar(select(func.count()).select_from(McpService).where(*conditions))
        connectors = await db.scalars(
            select(McpService)
            .where(*conditions)
            .order_by(McpService.name, McpService.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
        items = [await connector_option(db, c, actor) for c in connectors]
    return ExpertDependencyPage(items=items, total=total or 0, page=page)


async def dependency_detail(
    actor: BusinessActor,
    kind: Literal["skills", "connectors"],
    resource_id: UUID,
    request: Request,
    db: DB,
    version_id: UUID | None = None,
) -> ExpertDependencyOption:
    service.administrator(actor)
    if kind == "skills":
        skill = await db.get(Skill, resource_id)
        if skill and skill.tenant_id == actor.tenant.id:
            target = version_id or skill.default_version_id
            version = await db.get(SkillVersion, target) if target else None
            if version and version.skill_id == skill.id:
                return skill_option(skill, version)
    else:
        connector = await db.get(McpService, resource_id)
        if connector and connector.tenant_id == actor.tenant.id:
            return await connector_option(db, connector, actor)
    raise HTTPException(404, "能力不存在或已移除")


async def create(actor: BusinessActor, request: Request, db: DB, body: ExpertSave) -> ExpertView:
    service.administrator(actor)
    await require_category(db, actor.tenant.id, body.category)
    await service.validate_refs(db, actor, body.content, None)
    if body.content.avatar:
        body.content.avatar = uploaded_image(body.content.avatar)
    row = ExpertRecord(
        tenant_id=actor.tenant.id,
        name=body.content.name,
        description=body.content.description,
        category=body.category,
        draft=body.content.model_dump(mode="json"),
    )
    db.add(row)
    await db.flush()
    record(db, actor, "experts.create", row.id, row.name, {})
    result = await service.view(db, row)
    await db.flush()
    return result


async def detail(actor: BusinessActor, expert_id: UUID, request: Request, db: DB) -> ExpertView:
    service.administrator(actor)
    return await service.view(db, await service.get_expert(db, actor, expert_id))


async def delete_expert(
    actor: BusinessActor, expert_id: UUID, request: Request, db: DB, body: ExpertRevision
) -> Message:
    service.administrator(actor)
    row = await service.get_expert(db, actor, expert_id)
    service.revision(row, body.revision)
    record(db, actor, "experts.delete", row.id, row.name, {})
    await db.execute(delete(ExpertRelease).where(ExpertRelease.expert_id == row.id))
    await db.delete(row)
    await db.flush()
    return Message(message="专家已删除")


async def refresh_skills(
    actor: BusinessActor, expert_id: UUID, request: Request, db: DB, body: ExpertSkillRefresh
) -> ExpertView:
    service.administrator(actor)
    digest = dependency_updates.fingerprint(
        "expert.refresh_skills", expert_id, body.model_dump(mode="json")
    )
    if await dependency_updates.replay(db, actor, body.request_id, digest):
        return await service.view(db, await service.get_expert(db, actor, expert_id))
    row = await service.get_expert(db, actor, expert_id)
    service.revision(row, body.revision)
    if body.changes is not None:
        updated = await dependency_updates.apply(
            db,
            actor,
            [ExpertDraftSelection(expert_id=row.id, revision=body.revision, changes=body.changes)],
        )
        dependency_updates.remember(
            db, actor, body.request_id, digest, "expert.refresh_skills", row.id, updated
        )
        result = await service.view(db, row)
        await db.flush()
        return result
    content = ExpertContent.model_validate(row.draft)
    changed = 0
    for ref in content.skills:
        skill = await db.get(Skill, ref.skill_id)
        if not skill or skill.tenant_id != actor.tenant.id or (not skill.default_version_id):
            continue
        version = await db.get(SkillVersion, skill.default_version_id)
        if not version or version.skill_id != skill.id or version.status != "published":
            continue
        if ref.version_id != version.id or ref.sha256 != version.sha256:
            (ref.version_id, ref.sha256) = (version.id, version.sha256)
            changed += 1
    if changed:
        row.draft = content.model_dump(mode="json")
        row.revision += 1
        record(db, actor, "experts.refresh_skills", row.id, row.name, {"count": str(changed)})
    result = await service.view(db, row)
    await db.flush()
    return result


async def update(
    actor: BusinessActor, expert_id: UUID, request: Request, db: DB, body: ExpertUpdate
) -> ExpertView:
    service.administrator(actor)
    row = await service.get_expert(db, actor, expert_id)
    service.revision(row, body.revision)
    await require_category(db, actor.tenant.id, body.category)
    await service.validate_refs(db, actor, body.content, ExpertContent.model_validate(row.draft))
    if row.category != body.category:
        row.metadata_revision += 1
    row.category = body.category
    if body.content.avatar and body.content.avatar != row.draft.get("avatar", ""):
        body.content.avatar = uploaded_image(body.content.avatar)
    (row.name, row.description) = (body.content.name, body.content.description)
    row.draft = body.content.model_dump(mode="json")
    row.revision += 1
    record(db, actor, "experts.update", row.id, row.name, {})
    result = await service.view(db, row)
    await db.flush()
    return result


async def update_scope(
    actor: BusinessActor, expert_id: UUID, request: Request, db: DB, body: ExpertScope
) -> ExpertView:
    service.administrator(actor)
    row = await service.get_expert(db, actor, expert_id)
    service.revision(row, body.revision)
    await scope(db, actor, body)
    (row.audience, row.member_ids) = (body.audience, [str(v) for v in body.member_ids])
    row.revision += 1
    record(db, actor, "experts.scope", row.id, row.name, {"audience": row.audience})
    result = await service.view(db, row)
    await db.flush()
    return result


async def publish(
    actor: BusinessActor, expert_id: UUID, request: Request, db: DB, body: ExpertPublish
) -> ExpertView:
    service.administrator(actor)
    row = await service.get_expert(db, actor, expert_id)
    service.revision(row, body.revision)
    content = ExpertContent.model_validate(row.draft)
    if not (await service.check(db, row, content)).can_publish:
        raise HTTPException(409, "请填写工作指令并修复必需依赖后发布")
    if await db.scalar(
        select(ExpertRelease.id).where(
            ExpertRelease.expert_id == row.id, ExpertRelease.version == body.version
        )
    ):
        raise HTTPException(409, "此版本号已存在，请填写新的版本号")
    from app.modules.experts.connector_contracts import capture
    from app.modules.mcp.credentials import owner

    contracts = {}
    capabilities = {}
    locked_tools = {}
    from app.modules.experts.connector_contracts import capture_all

    for ref in content.connectors:
        connector = await db.get(McpService, ref.connector_id)
        locked = await capture(
            db, ref.connector_id, ref.tools, owner(connector, actor) if connector else None
        )
        if ref.required and ref.tools is not None and (locked is None):
            raise HTTPException(409, "所选必需工具尚未验证或定义已变化，请刷新目录并确认启用后发布")
        if not connector:
            raise HTTPException(409, "连接器不可用，请刷新后重试")
        captured = await capture_all(db, connector, owner(connector, actor), ref.tools)
        if captured is None:
            if ref.tools is not None:
                raise HTTPException(409, "所选工具尚未验证，请刷新目录并确认开放后发布")
            continue
        (names, proof) = captured
        locked_tools[ref.key] = names
        capabilities[ref.key] = proof
        contracts[ref.key] = (
            await capture(db, ref.connector_id, names, owner(connector, actor)) or {}
        )
    (manifest, refs, sha) = service.release_payload(
        row, content, body.version, contracts, capabilities, locked_tools
    )
    release = ExpertRelease(
        expert_id=row.id,
        version=body.version,
        manifest=manifest,
        dependency_refs=refs,
        sha256=sha,
        content=row.draft,
        release_notes=body.release_notes,
        publisher_name=actor.user.name,
    )
    db.add(release)
    await db.flush()
    row.current_release_id = release.id
    row.revision += 1
    record(
        db,
        actor,
        "experts.publish",
        row.id,
        row.name,
        {"release_id": str(release.id), "version": release.version},
    )
    result = await service.view(db, row)
    await db.flush()
    return result


async def withdraw(
    actor: BusinessActor, expert_id: UUID, request: Request, db: DB, body: ExpertRevision
) -> ExpertView:
    service.administrator(actor)
    row = await service.get_expert(db, actor, expert_id)
    service.revision(row, body.revision)
    if not row.current_release_id:
        raise HTTPException(409, "专家当前未发布")
    record(
        db, actor, "experts.withdraw", row.id, row.name, {"release_id": str(row.current_release_id)}
    )
    row.current_release_id = None
    row.revision += 1
    result = await service.view(db, row)
    await db.flush()
    return result
