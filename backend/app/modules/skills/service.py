from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor
from app.modules.skills.categories import require_category
from app.modules.skills.icons import resolved_icon
from app.modules.skills.models import Skill, SkillDistribution, SkillVersion
from app.modules.skills.schemas import SkillScope, SkillVersionView, SkillView


def administrator(actor: BusinessActor) -> None:
    if actor.member.role != "administrator":
        raise HTTPException(403, "此操作仅限管理员")


def allowed(skill: Skill, actor: BusinessActor) -> bool:
    return (
        actor.member.role == "administrator"
        or skill.audience == "organization"
        or skill.audience == "selected"
        and str(actor.member.id) in skill.member_ids
    )


async def scope(db: AsyncSession, actor: BusinessActor, body: SkillScope) -> None:
    if body.member_ids:
        valid = set(
            await db.scalars(
                select(Membership.id).where(
                    Membership.tenant_id == actor.tenant.id,
                    Membership.status == "active",
                    Membership.id.in_(body.member_ids),
                )
            )
        )
        if valid != set(body.member_ids):
            raise HTTPException(422, "请选择当前组织的有效成员")


async def get_skill(db: AsyncSession, actor: BusinessActor, skill_id: UUID) -> Skill:
    row = await db.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.tenant_id == actor.tenant.id)
    )
    if not row or not allowed(row, actor):
        raise HTTPException(404, "技能不存在或无权访问")
    return row


async def get_version(
    db: AsyncSession, actor: BusinessActor, skill: Skill, version_id: UUID
) -> SkillVersion:
    row = await db.scalar(
        select(SkillVersion).where(SkillVersion.id == version_id, SkillVersion.skill_id == skill.id)
    )
    if (
        not row
        or actor.member.role != "administrator"
        and (row.status != "published" or row.id != skill.default_version_id)
    ):
        raise HTTPException(404, "版本不存在或未发布")
    return row


async def view(db: AsyncSession, actor: BusinessActor, skill: Skill) -> SkillView:
    versions = list(
        await db.scalars(
            select(SkillVersion)
            .where(SkillVersion.skill_id == skill.id)
            .order_by(SkillVersion.created_at.desc(), SkillVersion.id)
        )
    )
    if actor.member.role != "administrator":
        versions = [
            v for v in versions if v.status == "published" and v.id == skill.default_version_id
        ]
        if not versions:
            raise HTTPException(404, "技能尚未发布")
    downloads = await db.scalar(
        select(func.count())
        .select_from(SkillDistribution)
        .where(SkillDistribution.skill_id == skill.id)
    )
    active = next(
        (v for v in versions if v.id == skill.default_version_id and v.status == "published"), None
    )
    return SkillView(
        category=skill.category,
        category_name=(await require_category(db, skill.tenant_id, skill.category)).name,
        icon=resolved_icon(skill.icon_selection, active.package_icon if active else ""),
        icon_selection=skill.icon_selection if actor.member.role == "administrator" else None,
        id=skill.id,
        name=skill.name,
        display_name=skill.display_name,
        description=skill.description,
        audience=skill.audience,
        member_ids=skill.member_ids if actor.member.role == "administrator" else [],
        revision=skill.revision,
        default_version_id=skill.default_version_id,
        versions=[SkillVersionView.model_validate(v) for v in versions],
        downloads=downloads or 0,
        created_at=skill.created_at,
    )
