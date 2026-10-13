"""Read-only expert distribution. Dependency permissions remain in their owning domains."""

from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field, SerializerFunctionWrapHandler, model_serializer
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.auth.service import DB, now
from app.modules.desktop import adoptions
from app.modules.desktop.errors import DesktopError, fail
from app.modules.desktop.resources import EXPERTS_CATALOG, NativeActor, authorize
from app.modules.desktop.schemas import DesktopErrorResponse
from app.modules.desktop_mcp.schemas import ConnectionState
from app.modules.desktop_mcp.service import connection_state, get_service
from app.modules.desktop_skills.service import current as current_skill
from app.modules.desktop_skills.service import exact as exact_skill
from app.modules.experts.categories import CategoryId, category_rows, require_category
from app.modules.experts.connector_access import connector_endpoint
from app.modules.experts.models import ExpertRecord, ExpertRelease
from app.modules.experts.schemas import (
    Digest,
    ExpertCategory,
    ExpertDependencyRefs,
    ExpertInput,
    ExpertManifestV1,
)


class DesktopExpertRelease(BaseModel):
    id: UUID
    version: str
    sha256: str


class DesktopExpert(BaseModel):
    contract_version: Literal[1, 2, 3] = 1
    expert_id: UUID
    name: str
    description: str
    avatar: str
    tags: list[str]
    category: ExpertCategory
    metadata_revision: int
    release: DesktopExpertRelease


class ExpertEnvelope(DesktopExpert):
    manifest: ExpertManifestV1
    dependency_refs: ExpertDependencyRefs


class DesktopExpertCategory(ExpertCategory):
    count: int


class DesktopExpertPage(BaseModel):
    items: list[DesktopExpert]
    total: int
    page: int
    page_size: int = 20


class ExpertProof(ExpertInput):
    access_version: Literal[1, 2, 3] = 1
    release_id: UUID
    sha256: Digest


class ExpertAdoptInput(ExpertProof):
    request_id: UUID
    access_version: Literal[2, 3] = 2


class InstalledExpert(ExpertProof):
    expert_id: UUID


class ExpertUpdates(ExpertInput):
    access_version: Literal[1, 2, 3] = 1
    items: list[InstalledExpert] = Field(max_length=100)


class ExpertUpdateState(BaseModel):
    expert_id: UUID
    status: Literal["current", "update_available", "unavailable"]
    expert: DesktopExpert | None = None
    adopted_usable: bool | None = None
    update_available: bool | None = None

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        result = cast(dict[str, Any], handler(self))
        for field in ("adopted_usable", "update_available"):
            if getattr(self, field) is None:
                result.pop(field, None)
        return result


class ExpertUpdatesView(BaseModel):
    items: list[ExpertUpdateState]


class ResolvedExpertDependency(BaseModel):
    kind: Literal["skills", "connectors"]
    key: str
    required: bool
    status: Literal[
        "available",
        "unavailable",
        "version_conflict",
        "connection_required",
        "unverified",
        "temporary_error",
    ]
    action: Literal["none", "contact_admin", "configure", "authorize", "retry", "verify"]
    resource_id: UUID | None = None
    version_state: Literal["current", "superseded"] | None = None
    update_available: bool | None = None
    version_id: UUID | None = None
    sha256: str | None = None
    connection: ConnectionState | None = None
    mcp_endpoint: str | None = None
    tools: list[str] | None = None
    change_kind: Literal["contract", "behavior"] | None = None


class ExpertResolution(ExpertProof):
    update_available: bool | None = None
    checked_at: str
    can_prepare: bool
    dependencies: list[ResolvedExpertDependency]


bearer = HTTPBearer(
    scheme_name="ExpertsResource",
    auto_error=False,
    description="由 desktop/resource-tokens 申请 experts:catalog。仅主进程持有。",
)
router = APIRouter(
    prefix="/api/v1/desktop/experts",
    tags=["desktop-experts"],
    dependencies=[Depends(bearer)],
    responses={
        status: {"model": DesktopErrorResponse} for status in (401, 403, 404, 409, 422, 503)
    },
)


def visibility(actor: NativeActor, q: str = "") -> list[ColumnElement[bool]]:
    scopes = [
        ExpertRecord.audience == "organization",
        (ExpertRecord.audience == "selected")
        & ExpertRecord.member_ids.contains([str(actor.member.id)]),
    ]
    if actor.member.role == "administrator":
        scopes.append(ExpertRecord.audience == "administrators")
    conditions = [
        ExpertRecord.tenant_id == actor.tenant.id,
        or_(*scopes),
        ExpertRelease.expert_id == ExpertRecord.id,
        ExpertRelease.id == ExpertRecord.current_release_id,
    ]
    if q.strip():
        conditions.append(
            or_(
                ExpertRelease.manifest["name"].astext.icontains(q.strip(), autoescape=True),
                ExpertRelease.manifest["description"].astext.icontains(q.strip(), autoescape=True),
            )
        )
    return conditions


async def current(
    db: AsyncSession, actor: NativeActor, expert_id: UUID
) -> tuple[ExpertRecord, ExpertRelease]:
    result = (
        await db.execute(
            select(ExpertRecord, ExpertRelease).where(
                *visibility(actor), ExpertRecord.id == expert_id
            )
        )
    ).first()
    if result is None:
        fail(404, "expert_unavailable", "专家不可用或未获授权")
    return result[0], result[1]


async def exact(
    db: AsyncSession,
    actor: NativeActor,
    expert_id: UUID,
    release_id: UUID,
    *,
    access_version: int = 1,
    sha256: str | None = None,
) -> tuple[ExpertRecord, ExpertRelease]:
    row, recommended = await current(db, actor, expert_id)
    release = recommended
    if recommended.id != release_id:
        if access_version not in {2, 3}:
            fail(409, "expert_release_changed", "专家发布已变化，请刷新后重新确认")
        historical = await db.get(ExpertRelease, release_id)
        if (
            not historical
            or historical.expert_id != row.id
            or not await adoptions.proof(
                db, actor, "experts", row.id, historical.id, historical.sha256
            )
        ):
            fail(404, "expert_release_unavailable", "此精确发布不可用")
        release = historical
    if sha256 is not None and release.sha256 != sha256:
        fail(409, "expert_release_changed", "专家摘要不一致，请重新确认精确发布")
    return row, release


async def overview(db: AsyncSession, row: ExpertRecord, release: ExpertRelease) -> DesktopExpert:
    category = await require_category(db, row.tenant_id, row.category)
    return DesktopExpert(
        contract_version=3
        if any(r.get("reference_version") == 3 for r in release.dependency_refs["connectors"])
        else 2
        if any(r.get("tools") is not None for r in release.dependency_refs["connectors"])
        else 1,
        expert_id=row.id,
        **{k: release.manifest[k] for k in ("name", "description", "avatar", "tags")},
        category=ExpertCategory(id=category.id, name=category.name),
        metadata_revision=row.metadata_revision,
        release=DesktopExpertRelease(id=release.id, version=release.version, sha256=release.sha256),
    )


@router.get(
    "/categories",
    response_model=list[DesktopExpertCategory],
    summary="后台类别顺序与当前成员可见数量",
)
async def categories(
    request: Request, db: DB, q: str = Query("", max_length=100)
) -> list[DesktopExpertCategory]:
    actor = await authorize(request, db, EXPERTS_CATALOG)
    counts: dict[str, int] = {
        key: count
        for key, count in (
            (
                await db.execute(
                    select(ExpertRecord.category, func.count())
                    .select_from(ExpertRecord, ExpertRelease)
                    .where(*visibility(actor, q))
                    .group_by(ExpertRecord.category)
                )
            ).all()
        )
    }
    return [
        DesktopExpertCategory(id=c.id, name=c.name, count=counts.get(c.id, 0))
        for c in await category_rows(db, actor.tenant.id)
    ]


@router.get("", response_model=DesktopExpertPage)
async def catalog(
    request: Request,
    db: DB,
    q: str = Query("", max_length=100),
    category: CategoryId | None = None,
    page: int = Query(1, ge=1),
) -> DesktopExpertPage:
    actor = await authorize(request, db, EXPERTS_CATALOG)
    conditions = visibility(actor, q)
    if category:
        await require_category(db, actor.tenant.id, category)
        conditions.append(ExpertRecord.category == category)
    total = await db.scalar(
        select(func.count()).select_from(ExpertRecord, ExpertRelease).where(*conditions)
    )
    rows = (
        await db.execute(
            select(ExpertRecord, ExpertRelease)
            .where(*conditions)
            .order_by(ExpertRelease.created_at.desc(), ExpertRecord.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    return DesktopExpertPage(
        items=[await overview(db, e, r) for e, r in rows], total=total or 0, page=page
    )


@router.post("/check-updates", response_model=ExpertUpdatesView)
async def updates(request: Request, db: DB, body: ExpertUpdates) -> ExpertUpdatesView:
    actor = await authorize(request, db, EXPERTS_CATALOG)
    rows = (
        await db.execute(
            select(ExpertRecord, ExpertRelease).where(
                *visibility(actor), ExpertRecord.id.in_([item.expert_id for item in body.items])
            )
        )
    ).all()
    available = {row.id: await overview(db, row, release) for row, release in rows}
    results = []
    for item in body.items:
        expert = available.get(item.expert_id)
        state = ExpertUpdateState(
            expert_id=item.expert_id,
            expert=expert,
            status="unavailable"
            if expert is None
            else "current"
            if expert.release.id == item.release_id and expert.release.sha256 == item.sha256
            else "update_available",
        )
        if body.access_version in {2, 3}:
            state.adopted_usable = False
            state.update_available = bool(expert and state.status == "update_available")
            try:
                await exact(
                    db,
                    actor,
                    item.expert_id,
                    item.release_id,
                    access_version=body.access_version,
                    sha256=item.sha256,
                )
                state.adopted_usable = True
            except DesktopError as exc:
                if exc.status_code not in {404, 409}:
                    raise
        results.append(state)
    return ExpertUpdatesView(items=results)


@router.get("/{expert_id}", response_model=ExpertEnvelope, response_model_exclude_none=True)
async def detail(
    expert_id: UUID,
    request: Request,
    db: DB,
    release_id: UUID | None = None,
    access_version: int = Query(1, ge=1, le=3),
) -> ExpertEnvelope:
    actor = await authorize(request, db, EXPERTS_CATALOG)
    row, release = (
        await current(db, actor, expert_id)
        if release_id is None
        else await exact(db, actor, expert_id, release_id, access_version=access_version)
    )
    return ExpertEnvelope(
        **(await overview(db, row, release)).model_dump(),
        manifest=release.manifest,
        dependency_refs=release.dependency_refs,
    )


@router.post(
    "/{expert_id}/resolve",
    response_model=ExpertResolution,
    response_model_exclude_none=True,
    summary="只读解析确切发布，不安装、不执行、不授予依赖权限",
)
async def resolve(expert_id: UUID, request: Request, db: DB, body: ExpertProof) -> ExpertResolution:
    # Same organization lock as publication and permission mutations. This POST performs no writes.
    actor = await authorize(request, db, EXPERTS_CATALOG, write=True)
    row, release = await exact(
        db,
        actor,
        expert_id,
        body.release_id,
        access_version=body.access_version,
        sha256=body.sha256,
    )
    dependencies = []
    for kind in ("skills", "connectors"):
        refs = {ref["key"]: ref for ref in release.dependency_refs[kind]}
        for requirement in release.manifest[kind]:
            ref = refs[requirement["key"]]
            state = ResolvedExpertDependency(
                kind=kind,
                key=requirement["key"],
                required=requirement["required"],
                status="unavailable",
                action="contact_admin",
            )
            try:
                if kind == "skills":
                    if body.access_version in {2, 3}:
                        skill, version = await exact_skill(
                            db,
                            actor,
                            UUID(ref["skill_id"]),
                            UUID(ref["version_id"]),
                            access_version=2,
                            sha256=ref["sha256"],
                            expert_id=row.id,
                            expert_release_id=release.id,
                        )
                        state.version_state = (
                            "current" if version.status == "published" else "superseded"
                        )
                        state.update_available = skill.default_version_id != version.id
                    else:
                        skill, version = await current_skill(db, actor, UUID(ref["skill_id"]))
                    state.resource_id = skill.id
                    if str(version.id) != ref["version_id"] or version.sha256 != ref["sha256"]:
                        state.status = "version_conflict"
                    else:
                        state.status, state.action = "available", "none"
                        state.version_id, state.sha256 = version.id, version.sha256
                else:
                    connector = await get_service(db, actor, UUID(ref["connector_id"]))
                    connection = await connection_state(request, db, connector, actor)
                    state.resource_id, state.connection = connector.id, connection
                    state.mcp_endpoint = connector_endpoint(
                        request, connector.id, expert_id, release.id, requirement["key"]
                    )
                    state.tools = ref.get("tools")
                    if (
                        ref.get("reference_version") == 3
                        and ref.get("capability_contracts") is None
                        and connection.status in {"connected", "unverified"}
                    ):
                        state.status, state.action = "unverified", "contact_admin"
                    elif connection.status == "connected":
                        if body.access_version in {2, 3}:
                            from app.modules.experts.connector_contracts import (
                                state as contract_state,
                            )
                            from app.modules.mcp.credentials import owner

                            if body.access_version == 3:
                                from app.modules.experts.connector_contracts import current_state_v3

                                state.status, state.change_kind = await current_state_v3(
                                    db, connector, owner(connector, actor), ref
                                )
                            else:
                                state.status = await contract_state(
                                    db, connector, owner(connector, actor), ref
                                )
                            state.action = (
                                "none"
                                if state.status == "available"
                                else "verify"
                                if state.status == "unverified"
                                and (
                                    ref.get("capability_contracts") is not None
                                    if body.access_version == 3
                                    else ref.get("tool_contracts") is not None
                                )
                                else "contact_admin"
                            )
                        else:
                            state.status, state.action = "available", "none"
                    elif connection.status == "unverified":
                        state.status, state.action = "unverified", "verify"
                    elif connection.status == "error":
                        state.status, state.action = "temporary_error", connection.action
                    else:
                        state.status, state.action = "connection_required", connection.action
            except DesktopError as exc:
                if exc.status_code == 409 and kind == "skills":
                    state.status = "version_conflict"
                elif exc.status_code != 404:
                    raise
            dependencies.append(state)
    new_unverified_keys = {
        ref["key"]
        for ref in release.dependency_refs["connectors"]
        if ref.get("reference_version") == 3 and ref.get("capability_contracts") is None
    }
    return ExpertResolution(
        release_id=release.id,
        sha256=release.sha256,
        access_version=body.access_version,
        update_available=(row.current_release_id != release.id)
        if body.access_version in {2, 3}
        else None,
        checked_at=now().isoformat(),
        can_prepare=all(
            not d.required
            or d.status == "available"
            or (
                body.access_version == 1
                and d.status == "unverified"
                and not (d.kind == "connectors" and d.key in new_unverified_keys)
            )
            for d in dependencies
        ),
        dependencies=dependencies,
    )


@router.post(
    "/{expert_id}/adopt",
    response_model=adoptions.AdoptionView,
    summary="显式采用精确专家发布，不执行或自动更新依赖",
)
async def adopt(
    expert_id: UUID, request: Request, db: DB, body: ExpertAdoptInput
) -> adoptions.AdoptionView:
    actor = await authorize(request, db, EXPERTS_CATALOG, write=True)
    row, release = await exact(
        db,
        actor,
        expert_id,
        body.release_id,
        access_version=body.access_version,
        sha256=body.sha256,
    )
    result = await adoptions.record(
        db, actor, "experts", row.id, release.id, release.sha256, body.request_id
    )
    await db.commit()
    return result
