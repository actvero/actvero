"""Resource operations shared by Web and organization-scoped management routes.

Authentication and the final transaction commit belong to the caller.
"""

import base64
import binascii
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Query, Request
from sqlalchemy import func, or_, select
from starlette.concurrency import run_in_threadpool

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, now
from app.modules.experts import dependency_updates
from app.modules.members.service import BusinessActor, record
from app.modules.skills import service
from app.modules.skills.categories import CategoryId, require_category
from app.modules.skills.icons import catalog
from app.modules.skills.models import Skill, SkillDistribution, SkillPackage, SkillVersion
from app.modules.skills.packages import MAX_PACKAGE, inspect_package, read_file
from app.modules.skills.schemas import (
    Audience,
    SkillAction,
    SkillDistributionPage,
    SkillDistributionView,
    SkillFile,
    SkillFileContent,
    SkillIconOption,
    SkillImport,
    SkillOverview,
    SkillPage,
    SkillPreview,
    SkillUpdate,
    SkillView,
)


async def icon_catalog(actor: BusinessActor, request: Request, db: DB) -> list[SkillIconOption]:
    service.administrator(actor)
    return [SkillIconOption.model_validate(item) for item in catalog()]


async def preview(actor: BusinessActor, request: Request, db: DB) -> SkillPreview:
    service.administrator(actor)
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_PACKAGE:
            raise HTTPException(413, "技能包不能超过 20 MB")
    package = await run_in_threadpool(inspect_package, bytes(data))
    return SkillPreview(
        package_icon=package.package_icon,
        icon_warning=package.icon_warning,
        name=package.name,
        description=package.description,
        skill_md=package.skill_md,
        files=[SkillFile.model_validate(f) for f in package.files],
        sha256=package.sha256,
        size=len(data),
    )


async def import_skill(
    actor: BusinessActor, request: Request, db: DB, body: SkillImport
) -> SkillView:
    service.administrator(actor)
    try:
        data = base64.b64decode(body.package_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "技能包编码无效") from None
    package = await run_in_threadpool(inspect_package, data)
    if body.skill_id:
        skill = await service.get_skill(db, actor, body.skill_id)
        if body.revision != skill.revision:
            raise HTTPException(409, "技能已被修改，请刷新后重试")
        if package.name != skill.name:
            raise HTTPException(422, "新版本的技能 name 必须与原技能一致")
        skill.revision += 1
    else:
        await service.scope(db, actor, body)
        await require_category(db, actor.tenant.id, body.category or "uncategorized")
        if await db.scalar(
            select(Skill.id).where(Skill.tenant_id == actor.tenant.id, Skill.name == package.name)
        ):
            raise HTTPException(409, "同名技能已存在，请进入详情上传新版本")
        skill = Skill(
            tenant_id=actor.tenant.id,
            name=package.name,
            display_name=body.display_name.strip(),
            description=body.description.strip(),
            category=body.category or "uncategorized",
            icon_selection=body.icon_selection.model_dump()
            if body.icon_selection
            else {"source": "auto"},
            audience=body.audience,
            member_ids=[str(m) for m in body.member_ids],
        )
        db.add(skill)
        await db.flush()
    if await db.scalar(
        select(SkillVersion.id).where(
            SkillVersion.skill_id == skill.id, SkillVersion.version == body.version
        )
    ):
        raise HTTPException(409, "此版本号已存在，不能覆盖原文件")
    version = SkillVersion(
        skill_id=skill.id,
        version=body.version,
        release_notes=body.release_notes,
        uploader_name=actor.user.name,
        sha256=package.sha256,
        size=len(data),
        files=package.files,
        skill_md=package.skill_md,
        package_icon=package.package_icon,
        icon_warning=package.icon_warning,
    )
    db.add(version)
    await db.flush()
    db.add(SkillPackage(version_id=version.id, data=data))
    record(db, actor, "skills.import", skill.id, skill.display_name, {"version": version.version})
    result = await service.view(db, actor, skill)
    await db.flush()
    return result


async def list_skills(
    actor: BusinessActor,
    request: Request,
    db: DB,
    audience: Audience | None = None,
    category: CategoryId | None = None,
    status: Literal["published", "unpublished"] | None = None,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
) -> SkillPage:
    conditions = [Skill.tenant_id == actor.tenant.id]
    if category:
        await require_category(db, actor.tenant.id, category)
        conditions.append(Skill.category == category)
    if audience:
        conditions.append(Skill.audience == audience)
    if status:
        published = (
            select(SkillVersion.id)
            .where(SkillVersion.skill_id == Skill.id, SkillVersion.status == "published")
            .exists()
        )
        conditions.append(published if status == "published" else ~published)
    if q:
        conditions.append(
            or_(
                Skill.name.icontains(q, autoescape=True),
                Skill.display_name.icontains(q, autoescape=True),
                Skill.description.icontains(q, autoescape=True),
            )
        )
    if actor.member.role != "administrator":
        conditions.extend(
            [
                or_(
                    Skill.audience == "organization",
                    (Skill.audience == "selected")
                    & Skill.member_ids.contains([str(actor.member.id)]),
                ),
                select(SkillVersion.id)
                .where(
                    SkillVersion.skill_id == Skill.id,
                    SkillVersion.status == "published",
                    SkillVersion.id == Skill.default_version_id,
                )
                .exists(),
            ]
        )
    total = await db.scalar(select(func.count()).select_from(Skill).where(*conditions))
    rows = await db.scalars(
        select(Skill)
        .where(*conditions)
        .order_by(Skill.created_at.desc(), Skill.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    return SkillPage(
        items=[await service.view(db, actor, s) for s in rows], total=total or 0, page=page
    )


async def distributions(
    actor: BusinessActor,
    request: Request,
    db: DB,
    skill_id: UUID | None = None,
    page: int = Query(default=1, ge=1),
) -> SkillDistributionPage:
    service.administrator(actor)
    conditions = [SkillDistribution.tenant_id == actor.tenant.id]
    if skill_id:
        conditions.append(SkillDistribution.skill_id == skill_id)
    total = await db.scalar(select(func.count()).select_from(SkillDistribution).where(*conditions))
    rows = await db.scalars(
        select(SkillDistribution)
        .where(*conditions)
        .order_by(SkillDistribution.created_at.desc(), SkillDistribution.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    return SkillDistributionPage(
        items=[SkillDistributionView.model_validate(r) for r in rows], total=total or 0, page=page
    )


async def detail(actor: BusinessActor, skill_id: UUID, request: Request, db: DB) -> SkillView:
    return await service.view(db, actor, await service.get_skill(db, actor, skill_id))


async def update(
    actor: BusinessActor, skill_id: UUID, request: Request, db: DB, body: SkillUpdate
) -> SkillView:
    service.administrator(actor)
    skill = await service.get_skill(db, actor, skill_id)
    if skill.revision != body.revision:
        raise HTTPException(409, "技能已被修改，请刷新后重试")
    await service.scope(db, actor, body)
    skill.display_name = body.display_name.strip()
    skill.description = body.description.strip()
    if body.category is not None:
        await require_category(db, actor.tenant.id, body.category)
        skill.category = body.category
    if body.icon_selection is not None:
        skill.icon_selection = body.icon_selection.model_dump()
    skill.audience = body.audience
    skill.member_ids = [str(m) for m in body.member_ids]
    skill.revision += 1
    record(
        db,
        actor,
        "skills.update",
        skill.id,
        skill.display_name,
        {"audience": skill.audience, "category": skill.category},
    )
    result = await service.view(db, actor, skill)
    await db.flush()
    return result


async def action(
    actor: BusinessActor,
    skill_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    body: SkillAction,
) -> SkillView:
    service.administrator(actor)
    digest = dependency_updates.fingerprint(
        "skill." + body.action,
        skill_id,
        {"version_id": str(version_id), **body.model_dump(mode="json")},
    )
    if await dependency_updates.replay(db, actor, body.request_id, digest):
        return await service.view(db, actor, await service.get_skill(db, actor, skill_id))
    skill = await service.get_skill(db, actor, skill_id)
    version = await service.get_version(db, actor, skill, version_id)
    if skill.revision != body.revision:
        raise HTTPException(409, "技能已被修改，请刷新后重试")
    updated = []
    if body.action == "publish":
        if version.status == "published":
            raise HTTPException(409, "此版本已发布")
        updated = await dependency_updates.apply(db, actor, body.draft_updates, (skill, version))
        previous = list(
            await db.scalars(
                select(SkillVersion).where(
                    SkillVersion.skill_id == skill.id, SkillVersion.status == "published"
                )
            )
        )
        for old in previous:
            old.status = "superseded"
            record(
                db,
                actor,
                "skills.withdraw",
                skill.id,
                skill.display_name,
                {"version": old.version, "replaced_by": version.version},
            )
        await db.flush()
        version.status = "published"
        version.published_at = now()
        skill.default_version_id = version.id
    else:
        if version.status not in {"published", "superseded"}:
            raise HTTPException(409, "仅生效或已替代版本可以停止使用")
        version.status = "withdrawn"
        if skill.default_version_id == version.id:
            skill.default_version_id = None
    skill.revision += 1
    dependency_updates.remember(
        db, actor, body.request_id, digest, "skill." + body.action, skill.id, updated
    )
    record(
        db,
        actor,
        "skills." + body.action,
        skill.id,
        skill.display_name,
        {"version": version.version},
    )
    await db.flush()
    result = await service.view(db, actor, skill)
    await db.flush()
    return result


async def delete_draft(
    actor: BusinessActor, skill_id: UUID, version_id: UUID, request: Request, db: DB, revision: int
) -> Message:
    service.administrator(actor)
    skill = await service.get_skill(db, actor, skill_id)
    version = await service.get_version(db, actor, skill, version_id)
    if skill.revision != revision or version.status != "draft":
        raise HTTPException(409, "只能删除当前未发布草稿，请刷新后重试")
    await db.delete(version)
    skill.revision += 1
    record(
        db, actor, "skills.delete_draft", skill.id, skill.display_name, {"version": version.version}
    )
    await db.flush()
    return Message(message="草稿已删除")


async def overview(
    actor: BusinessActor, skill_id: UUID, version_id: UUID, request: Request, db: DB
) -> SkillOverview:
    skill = await service.get_skill(db, actor, skill_id)
    version = await service.get_version(db, actor, skill, version_id)
    return SkillOverview(content=version.skill_md)


async def file_content(
    actor: BusinessActor,
    skill_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    path: str = Query(max_length=500),
) -> SkillFileContent:
    skill = await service.get_skill(db, actor, skill_id)
    version = await service.get_version(db, actor, skill, version_id)
    package = await db.get(SkillPackage, version.id)
    assert package
    content = await run_in_threadpool(read_file, package.data, path)
    return SkillFileContent(path=path, content=content)


async def download_package(
    actor: BusinessActor, request: Request, db: DB, skill_id: UUID, version_id: UUID
) -> tuple[bytes, str, str]:
    skill = await service.get_skill(db, actor, skill_id)
    version = await service.get_version(db, actor, skill, version_id)
    package = await db.get(SkillPackage, version.id)
    assert package
    db.add(
        SkillDistribution(
            tenant_id=actor.tenant.id,
            skill_id=skill.id,
            skill_name=skill.display_name,
            version=version.version,
            actor_id=actor.user.id,
            actor_name=actor.user.name,
        )
    )
    await db.flush()
    return package.data, f"{skill.name}-{version.version}.zip", version.sha256
