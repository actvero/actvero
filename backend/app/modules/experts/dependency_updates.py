"""Atomic selected draft changes; publication and permissions stay independent."""

import hashlib
import json
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.experts import service
from app.modules.experts.dependency_schemas import DependencyCommandView, ExpertDraftSelection
from app.modules.experts.models import DependencyCommandReceipt, ExpertRecord
from app.modules.experts.schemas import ExpertContent
from app.modules.members.service import BusinessActor, record
from app.modules.skills.models import Skill, SkillVersion


def fingerprint(action: str, resource_id: UUID, body: dict[str, Any]) -> str:
    value = {"action": action, "resource_id": str(resource_id), "body": body}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def receipt(
    db: AsyncSession, actor: BusinessActor, request_id: UUID
) -> DependencyCommandReceipt | None:
    return cast(
        DependencyCommandReceipt | None,
        await db.scalar(
            select(DependencyCommandReceipt).where(
                DependencyCommandReceipt.tenant_id == actor.tenant.id,
                DependencyCommandReceipt.member_id == actor.member.id,
                DependencyCommandReceipt.request_id == request_id,
            )
        ),
    )


async def replay(
    db: AsyncSession, actor: BusinessActor, request_id: UUID | None, digest: str
) -> bool:
    if request_id is None:
        return False
    row = await receipt(db, actor, request_id)
    if row and row.fingerprint != digest:
        raise HTTPException(409, "该更新编号已用于其他内容，请先查询原回执")
    return row is not None


def view(row: DependencyCommandReceipt) -> DependencyCommandView:
    return DependencyCommandView.model_validate(row, from_attributes=True)


def remember(
    db: AsyncSession,
    actor: BusinessActor,
    request_id: UUID | None,
    digest: str,
    action: str,
    resource_id: UUID,
    updated: list[ExpertRecord],
) -> None:
    if request_id is not None:
        db.add(
            DependencyCommandReceipt(
                tenant_id=actor.tenant.id,
                member_id=actor.member.id,
                request_id=request_id,
                fingerprint=digest,
                action=action,
                resource_id=resource_id,
                updated_experts=[
                    {"expert_id": str(row.id), "revision": row.revision} for row in updated
                ],
            )
        )


async def apply(
    db: AsyncSession,
    actor: BusinessActor,
    selections: list[ExpertDraftSelection],
    publication: tuple[Skill, SkillVersion] | None = None,
) -> list[ExpertRecord]:
    pending = []
    # Validate the whole batch before modifying any draft. Tenant lock is held by caller.
    for selection in selections:
        row = await service.get_expert(db, actor, selection.expert_id)
        service.revision(row, selection.revision)
        content = ExpertContent.model_validate(row.draft)
        refs = {r.key: r for r in content.skills}
        for change in selection.changes:
            ref = refs.get(change.key)
            if (
                not ref
                or ref.version_id != change.from_version_id
                or ref.sha256 != change.from_sha256
            ):
                raise HTTPException(409, "专家依赖已变化，请重新预览所选草稿")
            skill = await db.get(Skill, ref.skill_id)
            version = await db.get(SkillVersion, change.to_version_id)
            if (
                not skill
                or skill.tenant_id != actor.tenant.id
                or not version
                or version.skill_id != skill.id
            ):
                raise HTTPException(422, "所选目标不是此技能的有效版本")
            if publication is not None:
                if (skill.id, version.id) != (publication[0].id, publication[1].id):
                    raise HTTPException(422, "只能更新本次发布的技能版本")
            elif skill.default_version_id != version.id or version.status != "published":
                raise HTTPException(409, "目标版本已变化，请重新预览后确认")
            if version.sha256 != change.to_sha256:
                raise HTTPException(409, "目标摘要已变化，请重新预览后确认")
            if ref.version_id == version.id and ref.sha256 == version.sha256:
                raise HTTPException(409, "此依赖已经是所选版本，请重新预览")
            ref.version_id, ref.sha256 = version.id, version.sha256
        pending.append((row, content))
    for row, content in pending:
        row.draft = content.model_dump(mode="json")
        row.revision += 1
        record(
            db,
            actor,
            "experts.refresh_skills",
            row.id,
            row.name,
            {"count": str(len(next(s.changes for s in selections if s.expert_id == row.id)))},
        )
    return [row for row, _ in pending]
