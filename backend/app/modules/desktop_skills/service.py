from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.desktop import adoptions
from app.modules.desktop.errors import fail
from app.modules.desktop.resources import NativeActor
from app.modules.desktop_skills.schemas import DesktopSkill, DesktopSkillVersion
from app.modules.skills.categories import CategoryId, category_view
from app.modules.skills.icons import resolved_icon
from app.modules.skills.models import Skill, SkillVersion


def visibility(actor: NativeActor, q: str = "") -> list[ColumnElement[bool]]:
    # Desktop administrators get the explicitly declared administrator scope,
    # never the Web administrator's blanket inspection bypass.
    scopes = [
        Skill.audience == "organization",
        (Skill.audience == "selected") & Skill.member_ids.contains([str(actor.member.id)]),
    ]
    if actor.member.role == "administrator":
        scopes.append(Skill.audience == "administrators")
    conditions = [
        Skill.tenant_id == actor.tenant.id,
        or_(*scopes),
        SkillVersion.skill_id == Skill.id,
        SkillVersion.id == Skill.default_version_id,
        SkillVersion.status == "published",
    ]
    if q.strip():
        conditions.append(
            or_(
                *[
                    column.icontains(q.strip(), autoescape=True)
                    for column in (Skill.name, Skill.display_name, Skill.description)
                ]
            )
        )
    return conditions


async def current(
    db: AsyncSession, actor: NativeActor, skill_id: UUID, version_id: UUID | None = None
) -> tuple[Skill, SkillVersion]:
    row = (
        await db.execute(
            select(Skill, SkillVersion).where(*visibility(actor), Skill.id == skill_id)
        )
    ).first()
    if row is None:
        fail(404, "skill_unavailable", "技能不可用或未获授权，请刷新目录")
    skill, version = row
    if version_id is not None and version.id != version_id:
        fail(409, "skill_version_changed", "生效版本已变化，请刷新详情后重新确认")
    return skill, version


def view(skill: Skill, version: SkillVersion) -> DesktopSkill:
    return DesktopSkill(
        id=skill.id,
        name=skill.name,
        display_name=skill.display_name,
        description=skill.description,
        category=category_view(skill.category_info),
        icon=resolved_icon(skill.icon_selection, version.package_icon),
        revision=skill.revision,
        current_version=DesktopSkillVersion.model_validate(version),
    )


def category_condition(category: CategoryId | None) -> list[ColumnElement[bool]]:
    return [Skill.category == category] if category else []


async def exact(
    db: AsyncSession,
    actor: NativeActor,
    skill_id: UUID,
    version_id: UUID,
    *,
    access_version: int = 1,
    sha256: str | None = None,
    expert_id: UUID | None = None,
    expert_release_id: UUID | None = None,
) -> tuple[Skill, SkillVersion]:
    if (expert_id is None) != (expert_release_id is None):
        fail(422, "invalid_expert_proof", "专家ID和精确发布ID必须同时提供")
    # Current resource availability + live audience checks still gate every historical request.
    skill, recommended = await current(db, actor, skill_id)
    if version_id == recommended.id:
        version = recommended
    elif access_version != 2:
        fail(409, "skill_version_changed", "生效版本已变化，请刷新详情后重新确认")
    else:
        historical = await db.get(SkillVersion, version_id)
        if not historical or historical.skill_id != skill.id or historical.status != "superseded":
            fail(404, "skill_version_unavailable", "此精确版本不可用，请联系管理员")
        version = historical
        qualified = await adoptions.proof(db, actor, "skills", skill.id, version.id, version.sha256)
        if not qualified and expert_id is not None and expert_release_id is not None:
            from app.modules.experts.desktop import exact as exact_expert

            _, release = await exact_expert(
                db, actor, expert_id, expert_release_id, access_version=2
            )
            qualified = any(
                ref["skill_id"] == str(skill.id)
                and ref["version_id"] == str(version.id)
                and ref["sha256"] == version.sha256
                for ref in release.dependency_refs["skills"]
            )
        if not qualified:
            fail(404, "skill_version_unavailable", "此精确版本不可用，请联系管理员")
    if sha256 is not None and version.sha256 != sha256:
        fail(409, "skill_version_changed", "包摘要不一致，请重新确认精确版本")
    return skill, version
