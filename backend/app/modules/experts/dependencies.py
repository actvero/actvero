"""Live display metadata; never included in immutable expert content or fetched upstream."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.experts.schemas import ExpertDependencyOption, ExpertToolOption
from app.modules.mcp.models import McpService
from app.modules.mcp.service import capability_view
from app.modules.members.service import BusinessActor
from app.modules.skills.icons import resolved_icon
from app.modules.skills.models import Skill, SkillVersion


def skill_option(skill: Skill, version: SkillVersion) -> ExpertDependencyOption:
    return ExpertDependencyOption(
        id=skill.id,
        name=skill.display_name,
        description=skill.description,
        version_id=version.id,
        version=version.version,
        sha256=version.sha256,
        icon=resolved_icon(skill.icon_selection, version.package_icon)["image"],
        update_available=bool(skill.default_version_id and skill.default_version_id != version.id),
        status="available"
        if skill.default_version_id is not None and version.status in {"published", "superseded"}
        else "version_conflict",
    )


async def connector_option(
    db: AsyncSession, connector: McpService, actor: BusinessActor
) -> ExpertDependencyOption:
    caps = await capability_view(db, connector, actor)
    return ExpertDependencyOption(
        id=connector.id,
        name=connector.display_name or connector.name,
        description=connector.description,
        icon=connector.icon,
        status="available" if connector.enabled else "unavailable",
        tools_discovered=caps.checked_at is not None,
        tools=[
            ExpertToolOption(
                key=c.key,
                name=c.name,
                description=c.description,
                enabled=connector.enabled and c.enabled,
            )
            for c in caps.items
            if c.kind == "tools"
        ],
    )
