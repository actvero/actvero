"""Organization workbench release commands using management credentials."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.management import service
from app.modules.management.resources import mutate_resource, read_resource
from app.modules.management.router import BEARER
from app.modules.management.schemas import ResourceResult
from app.modules.workbenches import operations
from app.modules.workbenches.packages import Package
from app.modules.workbenches.router import PACKAGE_BODY
from app.modules.workbenches.schemas import (
    WorkbenchCategory,
    WorkbenchConfigUpdate,
    WorkbenchMetadata,
    WorkbenchPage,
    WorkbenchPublish,
    WorkbenchRevision,
    WorkbenchScope,
    WorkbenchStatus,
    WorkbenchView,
)

router = APIRouter(prefix="/{org_id}/workbenches", dependencies=BEARER)
RequestId = Annotated[UUID, Header(alias="X-Management-Request-ID")]


async def read_upload(request: Request, db: DB, org_id: UUID) -> tuple[bytes, Package]:
    who = await service.actor(request, db)
    await service.organization(
        request, db, who, org_id, require_admin=True, write=True, allow_platform_elevation=False
    )
    # Release the tenant lock while receiving and validating the archive.
    await db.rollback()
    return await operations.read_package(request)


@router.get("", summary="查询组织工作台")
async def list_workbenches(
    org_id: UUID,
    request: Request,
    db: DB,
    category: Annotated[WorkbenchCategory | None, Query(description="按工作台分类筛选")] = None,
    status: Annotated[
        WorkbenchStatus | None, Query(description="draft、published 或 withdrawn")
    ] = None,
    q: str = Query(default="", max_length=100, description="搜索展示名称或包名"),
    page: int = Query(default=1, ge=1, le=100_000, description="页码"),
) -> ResourceResult[WorkbenchPage]:
    return await read_resource(
        request,
        db,
        org_id,
        operations.list_workbenches,
        allow_platform_elevation=False,
        category=category,
        status=status,
        q=q,
        page=page,
    )


@router.get("/{workbench_id}", summary="查看工作台详情和版本历史")
async def show_workbench(
    org_id: UUID, workbench_id: UUID, request: Request, db: DB
) -> ResourceResult[WorkbenchView]:
    return await read_resource(
        request,
        db,
        org_id,
        operations.detail,
        allow_platform_elevation=False,
        workbench_id=workbench_id,
    )


@router.post("", status_code=201, summary="上传安装包并创建工作台草稿", openapi_extra=PACKAGE_BODY)
async def create_workbench(
    org_id: UUID, request: Request, db: DB, request_id: RequestId
) -> ResourceResult[WorkbenchView]:
    data, package = await read_upload(request, db, org_id)
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        operations.create_workbench,
        allow_platform_elevation=False,
        request_body=data,
        data=data,
        package=package,
    )


@router.post(
    "/{workbench_id}/versions",
    status_code=201,
    summary="上传同一工作台的新版本草稿",
    openapi_extra=PACKAGE_BODY,
)
async def upload_workbench_version(
    org_id: UUID,
    workbench_id: UUID,
    request: Request,
    db: DB,
    request_id: RequestId,
    revision: int = Query(ge=1, description="工作台当前修订号"),
) -> ResourceResult[WorkbenchView]:
    data, package = await read_upload(request, db, org_id)
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        operations.upload_version,
        allow_platform_elevation=False,
        request_body=data,
        workbench_id=workbench_id,
        revision=revision,
        data=data,
        package=package,
    )


@router.put("/{workbench_id}", summary="更新工作台展示资料")
async def update_workbench(
    org_id: UUID,
    workbench_id: UUID,
    request: Request,
    db: DB,
    request_id: RequestId,
    body: WorkbenchMetadata,
) -> ResourceResult[WorkbenchView]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        operations.update_metadata,
        allow_platform_elevation=False,
        workbench_id=workbench_id,
        body=body,
    )


@router.put("/{workbench_id}/scope", summary="设置工作台使用范围")
async def update_workbench_scope(
    org_id: UUID,
    workbench_id: UUID,
    request: Request,
    db: DB,
    request_id: RequestId,
    body: WorkbenchScope,
) -> ResourceResult[WorkbenchView]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        operations.update_scope,
        allow_platform_elevation=False,
        workbench_id=workbench_id,
        body=body,
    )


@router.put("/{workbench_id}/runtime-config", summary="保存工作台运行配置")
async def configure_workbench(
    org_id: UUID,
    workbench_id: UUID,
    request: Request,
    db: DB,
    request_id: RequestId,
    body: WorkbenchConfigUpdate,
) -> ResourceResult[WorkbenchView]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        operations.update_runtime_config,
        allow_platform_elevation=False,
        workbench_id=workbench_id,
        body=body,
    )


@router.post("/{workbench_id}/versions/{version_id}/publish", summary="发布工作台版本")
async def publish_workbench(
    org_id: UUID,
    workbench_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    request_id: RequestId,
    body: WorkbenchPublish,
) -> ResourceResult[WorkbenchView]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        operations.publish,
        allow_platform_elevation=False,
        workbench_id=workbench_id,
        version_id=version_id,
        body=body,
    )


@router.post("/{workbench_id}/versions/{version_id}/withdraw", summary="下架当前工作台版本")
async def withdraw_workbench(
    org_id: UUID,
    workbench_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    request_id: RequestId,
    body: WorkbenchRevision,
) -> ResourceResult[WorkbenchView]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        operations.withdraw,
        allow_platform_elevation=False,
        workbench_id=workbench_id,
        version_id=version_id,
        body=body,
    )


@router.delete("/{workbench_id}/versions/{version_id}", summary="删除未发布的工作台版本草稿")
async def delete_workbench_draft(
    org_id: UUID,
    workbench_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    request_id: RequestId,
    revision: int = Query(ge=1, description="工作台当前修订号"),
) -> ResourceResult[Message]:
    return await mutate_resource(
        request,
        db,
        org_id,
        request_id,
        operations.delete_draft,
        allow_platform_elevation=False,
        workbench_id=workbench_id,
        version_id=version_id,
        revision=revision,
    )
