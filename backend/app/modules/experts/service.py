import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.experts.categories import require_category
from app.modules.experts.dependencies import connector_option
from app.modules.experts.models import ExpertRecord, ExpertRelease
from app.modules.experts.schemas import (
    ExpertCategory,
    ExpertCheck,
    ExpertContent,
    ExpertDependencyState,
    ExpertManifestV1,
    ExpertReleaseView,
    ExpertSummary,
    ExpertView,
)
from app.modules.mcp.models import McpService
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor
from app.modules.skills.models import Skill, SkillVersion
from app.modules.skills.service import administrator as administrator


async def get_expert(db: AsyncSession, actor: BusinessActor, expert_id: UUID) -> ExpertRecord:
    row = await db.get(ExpertRecord, expert_id)
    if row is None or row.tenant_id != actor.tenant.id:
        raise HTTPException(404, "专家不存在或无权访问")
    return row


def revision(row: ExpertRecord, expected: int) -> None:
    if row.revision != expected:
        raise HTTPException(409, "专家已被修改，请重新载入后重试")


def allowed(audience: str, member_ids: list[str], member: Membership) -> bool:
    return (
        audience == "organization"
        or (audience == "administrators" and member.role == "administrator")
        or (audience == "selected" and str(member.id) in member_ids)
    )


async def validate_refs(
    db: AsyncSession, actor: BusinessActor, content: ExpertContent, previous: ExpertContent | None
) -> None:
    """Allow an unchanged stale reference to be edited; never accept new foreign resources."""
    for kind in ("skills", "connectors"):
        old = getattr(previous, kind) if previous else []
        for ref in getattr(content, kind):
            if ref in old:
                continue
            if kind == "skills":
                skill = await db.get(Skill, ref.skill_id)
                version = await db.get(SkillVersion, ref.version_id)
                if (
                    not skill
                    or skill.tenant_id != actor.tenant.id
                    or not version
                    or version.skill_id != skill.id
                    or version.sha256 != ref.sha256
                    or not (
                        version.status == "published"
                        and skill.default_version_id == version.id
                        or version.status == "superseded"
                        and any(
                            r.skill_id == ref.skill_id
                            and r.version_id == ref.version_id
                            and r.sha256 == ref.sha256
                            for r in old
                        )
                    )
                ):
                    raise HTTPException(422, "请选择当前组织的生效技能版本")
            else:
                connector = await db.get(McpService, ref.connector_id)
                if not connector or connector.tenant_id != actor.tenant.id:
                    raise HTTPException(422, "请选择当前组织的连接器")
                if ref.tools is not None:
                    prior = next((r for r in old if r.connector_id == ref.connector_id), None)
                    retained = set(prior.tools or []) if prior else set()
                    details = await connector_option(db, connector, actor)
                    available = {t.key for t in details.tools if t.enabled}
                    if set(ref.tools) - retained - available:
                        raise HTTPException(422, "只能选用连接器已开放的工具，请刷新后重试")


async def check(
    db: AsyncSession,
    row: ExpertRecord,
    content: ExpertContent,
    connector_refs: list[dict[str, Any]] | None = None,
) -> ExpertCheck:
    members = [
        m
        for m in await db.scalars(
            select(Membership).where(
                Membership.tenant_id == row.tenant_id, Membership.status == "active"
            )
        )
        if allowed(row.audience, row.member_ids, m)
    ]
    dependencies = []
    for ref in content.skills:
        skill = await db.get(Skill, ref.skill_id)
        version = await db.get(SkillVersion, ref.version_id)
        valid = skill is not None and skill.tenant_id == row.tenant_id
        state = "unavailable"
        if valid and skill and version and version.skill_id == ref.skill_id:
            state = (
                "available"
                if (
                    skill.default_version_id is not None
                    and version.status in {"published", "superseded"}
                    and version.sha256 == ref.sha256
                )
                else "version_conflict"
            )
        dependencies.append(
            ExpertDependencyState(
                kind="skills",
                key=ref.key,
                label=ref.label,
                required=ref.required,
                status=state,
                update_available=bool(
                    skill
                    and skill.default_version_id
                    and skill.default_version_id != ref.version_id
                ),
                locked_version=version.version if valid and version else None,
                missing_members=sum(
                    not (valid and skill and allowed(skill.audience, skill.member_ids, m))
                    for m in members
                ),
            )
        )
    for connector_ref in content.connectors:
        connector = await db.get(McpService, connector_ref.connector_id)
        valid_connector = (
            connector is not None and connector.tenant_id == row.tenant_id and connector.enabled
        )
        contract_valid = True
        if valid_connector and connector_ref.tools is not None:
            from app.modules.experts.connector_contracts import capture

            contract_valid = (
                await capture(db, connector_ref.connector_id, connector_ref.tools) is not None
            )
        unverified = False
        locked_ref = next((r for r in connector_refs or [] if r["key"] == connector_ref.key), None)
        if valid_connector and connector is not None and locked_ref is not None:
            if locked_ref.get("reference_version") == 3:
                from app.modules.experts.connector_contracts import published_state_v3

                published_state, _ = await published_state_v3(db, connector, locked_ref)
            else:
                from app.modules.experts.connector_contracts import policy_state

                published_state = await policy_state(db, connector_ref.connector_id, locked_ref)
            contract_valid = published_state == "available"
            unverified = published_state == "unverified"
        dependencies.append(
            ExpertDependencyState(
                kind="connectors",
                key=connector_ref.key,
                label=connector_ref.label,
                required=connector_ref.required,
                status="available"
                if valid_connector and contract_valid
                else "unverified"
                if valid_connector and unverified
                else "version_conflict"
                if valid_connector
                else "unavailable",
                missing_members=sum(
                    not (
                        valid_connector
                        and connector is not None
                        and (
                            connector.audience == "organization"
                            or str(m.id) in connector.member_ids
                        )
                    )
                    for m in members
                ),
            )
        )
    return ExpertCheck(
        can_publish=bool(content.instructions)
        and all(not d.required or d.status == "available" for d in dependencies),
        instruction_missing=not bool(content.instructions),
        audience_count=len(members),
        dependencies=dependencies,
    )


async def summary(db: AsyncSession, row: ExpertRecord) -> ExpertSummary:
    release = (
        await db.get(ExpertRelease, row.current_release_id) if row.current_release_id else None
    )
    ever = release or await db.scalar(
        select(ExpertRelease).where(ExpertRelease.expert_id == row.id).limit(1)
    )
    category = await require_category(db, row.tenant_id, row.category)
    changed = not release or release.content != row.draft
    if release and not changed:
        from app.modules.experts.connector_contracts import capture, published_state_v3

        for ref in release.dependency_refs["connectors"]:
            if ref.get("reference_version") == 3:
                connector = await db.get(McpService, UUID(ref["connector_id"]))
                if (
                    not connector
                    or (await published_state_v3(db, connector, ref))[0] != "available"
                ):
                    changed = True
            elif ref.get("tool_contracts") is not None:
                current_contract = await capture(db, UUID(ref["connector_id"]), ref.get("tools"))
                if current_contract is not None and current_contract != ref["tool_contracts"]:
                    changed = True
    return ExpertSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        avatar=row.draft.get("avatar", ""),
        category=ExpertCategory(id=category.id, name=category.name),
        audience=row.audience,
        revision=row.revision,
        metadata_revision=row.metadata_revision,
        current_release=ExpertReleaseView.model_validate(release) if release else None,
        has_changes=changed,
        dependency_issues=sum(
            d.status != "available"
            for d in (
                await check(
                    db,
                    row,
                    ExpertContent.model_validate(release.content if release else row.draft),
                    release.dependency_refs["connectors"] if release else None,
                )
            ).dependencies
        ),
        status="published" if release else "withdrawn" if ever else "draft",
    )


async def view(db: AsyncSession, row: ExpertRecord) -> ExpertView:
    content = ExpertContent.model_validate(row.draft)
    releases = await db.scalars(
        select(ExpertRelease)
        .where(ExpertRelease.expert_id == row.id)
        .order_by(ExpertRelease.created_at.desc(), ExpertRelease.id)
    )
    return ExpertView(
        **(await summary(db, row)).model_dump(),
        content=content,
        member_ids=row.member_ids,
        releases=[ExpertReleaseView.model_validate(r) for r in releases],
        check=await check(db, row, content),
    )


def release_payload(
    row: ExpertRecord,
    content: ExpertContent,
    version: str,
    tool_contracts: dict[str, dict[str, str]] | None = None,
    capability_contracts: dict[str, dict[str, dict[str, dict[str, str]]]] | None = None,
    locked_tools: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    data = content.model_dump(mode="json")
    manifest = {
        "schemaVersion": 1,
        "id": str(row.id),
        "version": version,
        **{key: data[key] for key in ("name", "description", "avatar", "tags", "instructions")},
        "category": "general",
        "conversationStarters": data["conversation_starters"],
        "skills": [{k: r[k] for k in ("key", "label", "required", "load")} for r in data["skills"]],
        "connectors": [{k: r[k] for k in ("key", "label", "required")} for r in data["connectors"]],
    }
    refs = {
        "skills": [
            {k: r[k] for k in ("key", "skill_id", "version_id", "sha256")} for r in data["skills"]
        ],
        "connectors": [
            {
                **{k: r[k] for k in ("key", "connector_id")},
                "reference_version": 3,
                **(
                    {"tools": locked_tools[r["key"]]}
                    if locked_tools and r["key"] in locked_tools
                    else {"tools": r["tools"]}
                    if r["tools"] is not None
                    else {}
                ),
                **(
                    {"capability_contracts": capability_contracts[r["key"]]}
                    if capability_contracts is not None and r["key"] in capability_contracts
                    else {}
                ),
                **(
                    {"tool_contracts": tool_contracts[r["key"]]}
                    if tool_contracts is not None and r["key"] in tool_contracts
                    else {}
                ),
            }
            for r in data["connectors"]
        ],
    }
    manifest = ExpertManifestV1.model_validate(manifest).model_dump(mode="json")
    canonical = json.dumps(
        {"manifest": manifest, "dependency_refs": refs},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return manifest, refs, hashlib.sha256(canonical).hexdigest()
