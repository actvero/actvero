"""Management routes share resource operations with the Web API."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.desktop.errors import fail
from app.modules.experts import operations as experts_ops
from app.modules.experts.categories import CategoryId as ExpertCategoryId
from app.modules.experts.dependency_schemas import (
    DependencyCommandView,
    ExpertSkillRefresh,
)
from app.modules.experts.schemas import (
    ExpertDependencyOption,
    ExpertDependencyPage,
    ExpertPage,
    ExpertPublish,
    ExpertRevision,
    ExpertSave,
    ExpertScope,
    ExpertSkillImpactView,
    ExpertUpdate,
    ExpertView,
)
from app.modules.management import mcp_dispatch
from app.modules.management import service as management_service
from app.modules.management.maintenance_router import router as maintenance_router
from app.modules.management.models import ManagementCommand
from app.modules.management.resources import mutate_resource, read_resource
from app.modules.management.schemas import CommandStatus, ResourceResult
from app.modules.mcp import operations as mcp_ops
from app.modules.mcp.schemas import (
    McpCapabilities,
    McpCredentials,
    McpImport,
    McpImportPreview,
    McpImportRequest,
    McpPolicyInput,
    McpPresentationUpdate,
    McpServicePage,
    McpServiceUpdate,
    McpServiceView,
    McpServiceWrite,
)
from app.modules.skills import operations as skills_ops
from app.modules.skills.categories import CategoryId as SkillCategoryId
from app.modules.skills.schemas import (
    Audience,
    SkillAction,
    SkillDistributionPage,
    SkillFileContent,
    SkillIconOption,
    SkillImport,
    SkillOverview,
    SkillPage,
    SkillPreview,
    SkillUpdate,
    SkillView,
)

router = APIRouter(prefix="/api/v1/management/organizations", tags=["management-resources"])
router.include_router(maintenance_router)


@router.get("/{org_id}/skills/icon-catalog", response_model=ResourceResult[list[SkillIconOption]])
async def skills_icon_catalog(
    org_id: UUID, request: Request, db: DB
) -> ResourceResult[list[SkillIconOption]]:
    return await read_resource(request, db, org_id, skills_ops.icon_catalog)


@router.post("/{org_id}/skills/preview", response_model=ResourceResult[SkillPreview])
async def skills_preview(org_id: UUID, request: Request, db: DB) -> ResourceResult[SkillPreview]:
    return await read_resource(request, db, org_id, skills_ops.preview)


@router.post("/{org_id}/skills/import", response_model=ResourceResult[SkillView])
async def skills_import_skill(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    request: Request,
    db: DB,
    body: SkillImport,
) -> ResourceResult[SkillView]:
    return await mutate_resource(
        request, db, org_id, request_id, skills_ops.import_skill, body=body
    )


@router.get("/{org_id}/skills", response_model=ResourceResult[SkillPage])
async def skills_list_skills(
    org_id: UUID,
    request: Request,
    db: DB,
    audience: Audience | None = None,
    category: SkillCategoryId | None = None,
    status: Literal["published", "unpublished"] | None = None,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
) -> ResourceResult[SkillPage]:
    return await read_resource(
        request,
        db,
        org_id,
        skills_ops.list_skills,
        audience=audience,
        category=category,
        status=status,
        q=q,
        page=page,
    )


@router.get("/{org_id}/skills/distributions", response_model=ResourceResult[SkillDistributionPage])
async def skills_distributions(
    org_id: UUID,
    request: Request,
    db: DB,
    skill_id: UUID | None = None,
    page: int = Query(default=1, ge=1),
) -> ResourceResult[SkillDistributionPage]:
    return await read_resource(
        request, db, org_id, skills_ops.distributions, skill_id=skill_id, page=page
    )


@router.get("/{org_id}/skills/{skill_id}", response_model=ResourceResult[SkillView])
async def skills_detail(
    org_id: UUID, skill_id: UUID, request: Request, db: DB
) -> ResourceResult[SkillView]:
    return await read_resource(request, db, org_id, skills_ops.detail, skill_id=skill_id)


@router.put("/{org_id}/skills/{skill_id}", response_model=ResourceResult[SkillView])
async def skills_update(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    skill_id: UUID,
    request: Request,
    db: DB,
    body: SkillUpdate,
) -> ResourceResult[SkillView]:
    return await mutate_resource(
        request, db, org_id, request_id, skills_ops.update, skill_id=skill_id, body=body
    )


@router.post(
    "/{org_id}/skills/{skill_id}/versions/{version_id}/actions",
    response_model=ResourceResult[SkillView],
)
async def skills_action(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    skill_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    body: SkillAction,
) -> ResourceResult[SkillView]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        skills_ops.action,
        skill_id=skill_id,
        version_id=version_id,
        body=body,
    )


@router.delete(
    "/{org_id}/skills/{skill_id}/versions/{version_id}", response_model=ResourceResult[Message]
)
async def skills_delete_draft(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    skill_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    revision: int,
) -> ResourceResult[Message]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        skills_ops.delete_draft,
        skill_id=skill_id,
        version_id=version_id,
        revision=revision,
    )


@router.get(
    "/{org_id}/skills/{skill_id}/versions/{version_id}/overview",
    response_model=ResourceResult[SkillOverview],
)
async def skills_overview(
    org_id: UUID, skill_id: UUID, version_id: UUID, request: Request, db: DB
) -> ResourceResult[SkillOverview]:
    return await read_resource(
        request, db, org_id, skills_ops.overview, skill_id=skill_id, version_id=version_id
    )


@router.get(
    "/{org_id}/skills/{skill_id}/versions/{version_id}/file",
    response_model=ResourceResult[SkillFileContent],
)
async def skills_file_content(
    org_id: UUID,
    skill_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    path: str = Query(max_length=500),
) -> ResourceResult[SkillFileContent]:
    return await read_resource(
        request,
        db,
        org_id,
        skills_ops.file_content,
        skill_id=skill_id,
        version_id=version_id,
        path=path,
    )


@router.get("/{org_id}/mcp/services", response_model=ResourceResult[McpServicePage])
async def mcp_services(org_id: UUID, request: Request, db: DB) -> ResourceResult[McpServicePage]:
    return await read_resource(request, db, org_id, mcp_ops.services)


@router.post("/{org_id}/mcp/services", response_model=ResourceResult[McpServiceView])
async def mcp_create_service(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    request: Request,
    db: DB,
    body: McpServiceWrite,
) -> ResourceResult[McpServiceView]:
    return await mutate_resource(request, db, org_id, request_id, mcp_ops.create_service, body=body)


@router.put("/{org_id}/mcp/services/{service_id}", response_model=ResourceResult[McpServiceView])
async def mcp_update_service(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
    body: McpServiceUpdate,
) -> ResourceResult[McpServiceView]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_ops.update_service, service_id=service_id, body=body
    )


@router.delete("/{org_id}/mcp/services/{service_id}", response_model=ResourceResult[Message])
async def mcp_delete_service(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
    version: int = Query(ge=1),
) -> ResourceResult[Message]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        mcp_ops.delete_service,
        service_id=service_id,
        expected_version=version,
    )


@router.put(
    "/{org_id}/mcp/services/{service_id}/presentation",
    response_model=ResourceResult[McpServiceView],
)
async def mcp_presentation(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
    body: McpPresentationUpdate,
) -> ResourceResult[McpServiceView]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_ops.presentation, service_id=service_id, body=body
    )


@router.post("/{org_id}/mcp/import/preview", response_model=ResourceResult[McpImportPreview])
async def mcp_preview_import(
    org_id: UUID, request: Request, db: DB, body: McpImportRequest
) -> ResourceResult[McpImportPreview]:
    return await read_resource(request, db, org_id, mcp_ops.preview_import, body=body)


@router.post("/{org_id}/mcp/import", response_model=ResourceResult[McpServicePage])
async def mcp_import_services(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    request: Request,
    db: DB,
    body: McpImportRequest | McpImport,
) -> ResourceResult[McpServicePage]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_ops.import_services, body=body
    )


@router.get("/{org_id}/mcp/export", response_model=ResourceResult[McpImport])
async def mcp_export_services(org_id: UUID, request: Request, db: DB) -> ResourceResult[McpImport]:
    return await read_resource(request, db, org_id, mcp_ops.export_services)


@router.get(
    "/{org_id}/mcp/services/{service_id}/capabilities",
    response_model=ResourceResult[McpCapabilities],
)
async def mcp_capabilities(
    org_id: UUID, service_id: UUID, request: Request, db: DB
) -> ResourceResult[McpCapabilities]:
    return await read_resource(request, db, org_id, mcp_ops.capabilities, service_id=service_id)


@router.post(
    "/{org_id}/mcp/services/{service_id}/discover", response_model=ResourceResult[McpCapabilities]
)
async def mcp_discover(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
) -> ResourceResult[McpCapabilities]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_dispatch.discover, service_id=service_id
    )


@router.put("/{org_id}/mcp/services/{service_id}/policy", response_model=ResourceResult[Message])
async def mcp_policy(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
    body: McpPolicyInput,
) -> ResourceResult[Message]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_ops.policy, service_id=service_id, body=body
    )


@router.put(
    "/{org_id}/mcp/services/{service_id}/connection", response_model=ResourceResult[Message]
)
async def mcp_set_connection(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
    body: McpCredentials,
) -> ResourceResult[Message]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_ops.set_connection, service_id=service_id, body=body
    )


@router.delete(
    "/{org_id}/mcp/services/{service_id}/connection", response_model=ResourceResult[Message]
)
async def mcp_disconnect(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
) -> ResourceResult[Message]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_ops.disconnect, service_id=service_id
    )


@router.get(
    "/{org_id}/experts/dependency-commands/{request_id}",
    response_model=ResourceResult[DependencyCommandView],
)
async def experts_dependency_receipt(
    org_id: UUID, request_id: UUID, request: Request, db: DB
) -> ResourceResult[DependencyCommandView]:
    return await read_resource(
        request, db, org_id, experts_ops.dependency_receipt, request_id=request_id
    )


@router.get("/{org_id}/experts/skill-impact", response_model=ResourceResult[ExpertSkillImpactView])
async def experts_skill_impact(
    org_id: UUID,
    request: Request,
    db: DB,
    skill_id: UUID,
    target_version_id: UUID | None = None,
    source_version_id: UUID | None = None,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> ResourceResult[ExpertSkillImpactView]:
    return await read_resource(
        request,
        db,
        org_id,
        experts_ops.skill_impact,
        skill_id=skill_id,
        target_version_id=target_version_id,
        source_version_id=source_version_id,
        q=q,
        page=page,
    )


@router.get("/{org_id}/experts", response_model=ResourceResult[ExpertPage])
async def experts_listing(
    org_id: UUID,
    request: Request,
    db: DB,
    q: str = Query("", max_length=100),
    category: ExpertCategoryId | None = None,
    status: Literal["published", "unpublished"] | None = None,
    page: int = Query(1, ge=1),
) -> ResourceResult[ExpertPage]:
    return await read_resource(
        request, db, org_id, experts_ops.listing, q=q, category=category, status=status, page=page
    )


@router.get("/{org_id}/experts/dependencies", response_model=ResourceResult[ExpertDependencyPage])
async def experts_options(
    org_id: UUID,
    request: Request,
    db: DB,
    kind: Literal["skills", "connectors"],
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> ResourceResult[ExpertDependencyPage]:
    return await read_resource(request, db, org_id, experts_ops.options, kind=kind, q=q, page=page)


@router.get(
    "/{org_id}/experts/dependencies/{kind}/{resource_id}",
    response_model=ResourceResult[ExpertDependencyOption],
)
async def experts_dependency_detail(
    org_id: UUID,
    kind: Literal["skills", "connectors"],
    resource_id: UUID,
    request: Request,
    db: DB,
    version_id: UUID | None = None,
) -> ResourceResult[ExpertDependencyOption]:
    return await read_resource(
        request,
        db,
        org_id,
        experts_ops.dependency_detail,
        kind=kind,
        resource_id=resource_id,
        version_id=version_id,
    )


@router.post("/{org_id}/experts", response_model=ResourceResult[ExpertView])
async def experts_create(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    request: Request,
    db: DB,
    body: ExpertSave,
) -> ResourceResult[ExpertView]:
    return await mutate_resource(request, db, org_id, request_id, experts_ops.create, body=body)


@router.get("/{org_id}/experts/{expert_id}", response_model=ResourceResult[ExpertView])
async def experts_detail(
    org_id: UUID, expert_id: UUID, request: Request, db: DB
) -> ResourceResult[ExpertView]:
    return await read_resource(request, db, org_id, experts_ops.detail, expert_id=expert_id)


@router.delete("/{org_id}/experts/{expert_id}", response_model=ResourceResult[Message])
async def experts_delete_expert(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    expert_id: UUID,
    request: Request,
    db: DB,
    body: ExpertRevision,
) -> ResourceResult[Message]:
    return await mutate_resource(
        request, db, org_id, request_id, experts_ops.delete_expert, expert_id=expert_id, body=body
    )


@router.post(
    "/{org_id}/experts/{expert_id}/refresh-skills", response_model=ResourceResult[ExpertView]
)
async def experts_refresh_skills(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    expert_id: UUID,
    request: Request,
    db: DB,
    body: ExpertSkillRefresh,
) -> ResourceResult[ExpertView]:
    return await mutate_resource(
        request, db, org_id, request_id, experts_ops.refresh_skills, expert_id=expert_id, body=body
    )


@router.put("/{org_id}/experts/{expert_id}", response_model=ResourceResult[ExpertView])
async def experts_update(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    expert_id: UUID,
    request: Request,
    db: DB,
    body: ExpertUpdate,
) -> ResourceResult[ExpertView]:
    return await mutate_resource(
        request, db, org_id, request_id, experts_ops.update, expert_id=expert_id, body=body
    )


@router.put("/{org_id}/experts/{expert_id}/scope", response_model=ResourceResult[ExpertView])
async def experts_update_scope(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    expert_id: UUID,
    request: Request,
    db: DB,
    body: ExpertScope,
) -> ResourceResult[ExpertView]:
    return await mutate_resource(
        request, db, org_id, request_id, experts_ops.update_scope, expert_id=expert_id, body=body
    )


@router.post("/{org_id}/experts/{expert_id}/publish", response_model=ResourceResult[ExpertView])
async def experts_publish(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    expert_id: UUID,
    request: Request,
    db: DB,
    body: ExpertPublish,
) -> ResourceResult[ExpertView]:
    return await mutate_resource(
        request, db, org_id, request_id, experts_ops.publish, expert_id=expert_id, body=body
    )


@router.post("/{org_id}/experts/{expert_id}/withdraw", response_model=ResourceResult[ExpertView])
async def experts_withdraw(
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    org_id: UUID,
    expert_id: UUID,
    request: Request,
    db: DB,
    body: ExpertRevision,
) -> ResourceResult[ExpertView]:
    return await mutate_resource(
        request, db, org_id, request_id, experts_ops.withdraw, expert_id=expert_id, body=body
    )


@router.get("/{org_id}/commands/{request_id}", response_model=ResourceResult[CommandStatus])
async def command_status(
    org_id: UUID, request_id: UUID, request: Request, db: DB
) -> ResourceResult[CommandStatus]:
    who = await management_service.actor(request, db)
    actor, organization = await management_service.organization(
        request, db, who, org_id, require_admin=True
    )
    receipt = await db.get(ManagementCommand, (org_id, actor.user.id, request_id))
    if receipt is None:
        fail(404, "command_not_found", "未找到本人在此组织的请求")
    result = CommandStatus(
        request_id=receipt.request_id,
        operation=receipt.operation,
        status=receipt.status,
        result=receipt.result,
        created_at=receipt.created_at,
        finished_at=receipt.finished_at,
    )
    await db.commit()
    return ResourceResult(organization=organization, result=result)
