"""Additional organization maintenance operations shared with the Web API."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response
from pydantic import BaseModel

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.experts import category_operations as expert_categories
from app.modules.experts.categories import (
    ExpertCategoryDelete,
    ExpertCategoryMove,
    ExpertCategoryName,
    ExpertCategoryRename,
    ManagedExpertCategory,
)
from app.modules.management import mcp_dispatch, service
from app.modules.management.resources import mutate_resource, read_resource
from app.modules.management.schemas import ResourceResult
from app.modules.mcp import operations as mcp_ops
from app.modules.mcp.schemas import (
    McpActivityPage,
    McpContentInput,
    McpContents,
    McpContentView,
    McpResult,
    McpRun,
)
from app.modules.members.service import BusinessActor
from app.modules.skills import category_operations as skill_categories
from app.modules.skills import operations as skill_ops
from app.modules.skills import service as skills_service
from app.modules.skills.categories import (
    CategoryDelete,
    CategoryMove,
    CategoryName,
    CategoryRename,
    ManagedSkillCategory,
)
from app.modules.skills.models import SkillPackage

router = APIRouter()


@router.get(
    "/{org_id}/skills/categories", response_model=ResourceResult[list[ManagedSkillCategory]]
)
async def skills_category_categories(
    org_id: UUID, request: Request, db: DB
) -> ResourceResult[list[ManagedSkillCategory]]:
    return await read_resource(request, db, org_id, skill_categories.categories)


@router.post(
    "/{org_id}/skills/categories", response_model=ResourceResult[list[ManagedSkillCategory]]
)
async def skills_category_create(
    org_id: UUID,
    request: Request,
    db: DB,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    body: CategoryName,
) -> ResourceResult[list[ManagedSkillCategory]]:
    return await mutate_resource(
        request, db, org_id, request_id, skill_categories.create, body=body
    )


@router.patch(
    "/{org_id}/skills/categories/{category_id}",
    response_model=ResourceResult[list[ManagedSkillCategory]],
)
async def skills_category_rename(
    org_id: UUID,
    request: Request,
    db: DB,
    category_id: str,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    body: CategoryRename,
) -> ResourceResult[list[ManagedSkillCategory]]:
    return await mutate_resource(
        request, db, org_id, request_id, skill_categories.rename, category_id=category_id, body=body
    )


@router.post(
    "/{org_id}/skills/categories/{category_id}/move",
    response_model=ResourceResult[list[ManagedSkillCategory]],
)
async def skills_category_move(
    org_id: UUID,
    request: Request,
    db: DB,
    category_id: str,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    body: CategoryMove,
) -> ResourceResult[list[ManagedSkillCategory]]:
    return await mutate_resource(
        request, db, org_id, request_id, skill_categories.move, category_id=category_id, body=body
    )


@router.delete("/{org_id}/skills/categories/{category_id}", response_model=ResourceResult[Message])
async def skills_category_delete(
    org_id: UUID,
    request: Request,
    db: DB,
    category_id: str,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    body: CategoryDelete,
) -> ResourceResult[Message]:
    return await mutate_resource(
        request, db, org_id, request_id, skill_categories.delete, category_id=category_id, body=body
    )


@router.get(
    "/{org_id}/experts/categories", response_model=ResourceResult[list[ManagedExpertCategory]]
)
async def experts_category_categories(
    org_id: UUID, request: Request, db: DB
) -> ResourceResult[list[ManagedExpertCategory]]:
    return await read_resource(request, db, org_id, expert_categories.categories)


@router.post(
    "/{org_id}/experts/categories", response_model=ResourceResult[list[ManagedExpertCategory]]
)
async def experts_category_create(
    org_id: UUID,
    request: Request,
    db: DB,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    body: ExpertCategoryName,
) -> ResourceResult[list[ManagedExpertCategory]]:
    return await mutate_resource(
        request, db, org_id, request_id, expert_categories.create, body=body
    )


@router.patch(
    "/{org_id}/experts/categories/{category_id}",
    response_model=ResourceResult[list[ManagedExpertCategory]],
)
async def experts_category_rename(
    org_id: UUID,
    request: Request,
    db: DB,
    category_id: str,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    body: ExpertCategoryRename,
) -> ResourceResult[list[ManagedExpertCategory]]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        expert_categories.rename,
        category_id=category_id,
        body=body,
    )


@router.post(
    "/{org_id}/experts/categories/{category_id}/move",
    response_model=ResourceResult[list[ManagedExpertCategory]],
)
async def experts_category_move(
    org_id: UUID,
    request: Request,
    db: DB,
    category_id: str,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    body: ExpertCategoryMove,
) -> ResourceResult[list[ManagedExpertCategory]]:
    return await mutate_resource(
        request, db, org_id, request_id, expert_categories.move, category_id=category_id, body=body
    )


@router.delete("/{org_id}/experts/categories/{category_id}", response_model=ResourceResult[Message])
async def experts_category_delete(
    org_id: UUID,
    request: Request,
    db: DB,
    category_id: str,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
    body: ExpertCategoryDelete,
) -> ResourceResult[Message]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        expert_categories.delete,
        category_id=category_id,
        body=body,
    )


class DownloadReceipt(BaseModel):
    skill_id: UUID
    version_id: UUID
    filename: str
    sha256: str
    size: int


async def record_download(
    actor: BusinessActor, request: Request, db: DB, skill_id: UUID, version_id: UUID
) -> DownloadReceipt:
    data, filename, checksum = await skill_ops.download_package(
        actor, request, db, skill_id, version_id
    )
    return DownloadReceipt(
        skill_id=skill_id, version_id=version_id, filename=filename, sha256=checksum, size=len(data)
    )


@router.post(
    "/{org_id}/skills/{skill_id}/versions/{version_id}/download",
    response_class=Response,
    responses={
        200: {"content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def download(
    org_id: UUID,
    skill_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
) -> Response:
    receipt = await mutate_resource(
        request, db, org_id, request_id, record_download, skill_id=skill_id, version_id=version_id
    )
    # Reauthorize every byte delivery, including a successful receipt replay.
    who = await service.actor(request, db)
    actor, _ = await service.organization(request, db, who, org_id, require_admin=True)
    skill = await skills_service.get_skill(db, actor, skill_id)
    await skills_service.get_version(db, actor, skill, version_id)
    package = await db.get(SkillPackage, version_id)
    assert package
    data = package.data
    info = DownloadReceipt.model_validate(receipt.result)
    await db.commit()
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{info.filename}"',
            "X-Content-SHA256": info.sha256,
            "X-Management-Request-ID": str(request_id),
            "X-Organization-ID": str(org_id),
        },
    )


@router.post("/{org_id}/mcp/services/{service_id}/run", response_model=ResourceResult[McpResult])
async def mcp_run(
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
    body: McpRun,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
) -> ResourceResult[McpResult]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        mcp_dispatch.run,
        service_id=service_id,
        body=body,
        retain_result=False,
    )


@router.get("/{org_id}/mcp/activities", response_model=ResourceResult[McpActivityPage])
async def mcp_activities(
    org_id: UUID,
    request: Request,
    db: DB,
    category: Literal["call", "connection"],
    page: int = Query(1, ge=1),
    service_id: UUID | None = None,
    result: Literal["success", "failed", "timeout"] | None = None,
    q: str = Query("", max_length=100),
    since: datetime | None = None,
    until: datetime | None = None,
) -> ResourceResult[McpActivityPage]:
    return await read_resource(
        request,
        db,
        org_id,
        mcp_ops.activities,
        category=category,
        page=page,
        service_id=service_id,
        result=result,
        q=q,
        since=since,
        until=until,
    )


@router.get("/{org_id}/mcp/contents", response_model=ResourceResult[McpContents])
async def mcp_contents(org_id: UUID, request: Request, db: DB) -> ResourceResult[McpContents]:
    return await read_resource(request, db, org_id, mcp_ops.list_contents)


@router.post("/{org_id}/mcp/contents", response_model=ResourceResult[McpContentView])
async def mcp_content_create(
    org_id: UUID,
    request: Request,
    db: DB,
    body: McpContentInput,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
) -> ResourceResult[McpContentView]:
    return await mutate_resource(request, db, org_id, request_id, mcp_ops.create_content, body=body)


@router.put("/{org_id}/mcp/contents/{content_id}", response_model=ResourceResult[McpContentView])
async def mcp_content_update(
    org_id: UUID,
    content_id: UUID,
    request: Request,
    db: DB,
    body: McpContentInput,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
) -> ResourceResult[McpContentView]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_ops.update_content, body=body, content_id=content_id
    )


@router.delete("/{org_id}/mcp/contents/{content_id}", response_model=ResourceResult[Message])
async def mcp_content_delete(
    org_id: UUID,
    content_id: UUID,
    request: Request,
    db: DB,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
) -> ResourceResult[Message]:
    return await mutate_resource(
        request, db, org_id, request_id, mcp_ops.delete_content, content_id=content_id
    )
