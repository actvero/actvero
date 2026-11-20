from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB
from app.modules.members.service import Access
from app.modules.workbenches import operations
from app.modules.workbenches.packages import Package
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

router = APIRouter(prefix="/api/v1/workbenches", tags=["workbenches"])
PACKAGE_BODY = {
    "requestBody": {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
}


async def administrator(request: Request, db: AsyncSession, *, write: bool = False) -> Access:
    actor = await own_access(request, db, write=write, allow_platform_elevation=False)
    if actor.member.role != "administrator":
        raise HTTPException(403, "此操作仅限当前组织的管理员")
    return actor


async def upload(request: Request, db: AsyncSession) -> tuple[bytes, Package]:
    await administrator(request, db)
    await db.rollback()
    return await operations.read_package(request)


@router.get("", summary="查看当前组织的工作台")
async def list_workbenches(
    request: Request,
    db: DB,
    category: WorkbenchCategory | None = None,
    status: WorkbenchStatus | None = None,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1, le=100_000),
) -> WorkbenchPage:
    actor = await administrator(request, db)
    return await operations.list_workbenches(request, db, actor, category, status, q, page)


@router.post("", status_code=201, summary="上传工作台并创建草稿", openapi_extra=PACKAGE_BODY)
async def create_workbench(request: Request, db: DB, _csrf: Mutation) -> WorkbenchView:
    data, package = await upload(request, db)
    actor = await administrator(request, db, write=True)
    result = await operations.create_workbench(request, db, actor, data, package)
    await db.commit()
    return result


@router.get("/{workbench_id}", summary="查看工作台资料和版本历史")
async def detail(workbench_id: UUID, request: Request, db: DB) -> WorkbenchView:
    actor = await administrator(request, db)
    return await operations.detail(workbench_id, request, db, actor)


@router.put("/{workbench_id}", summary="更新工作台展示资料")
async def update_metadata(
    workbench_id: UUID, body: WorkbenchMetadata, request: Request, db: DB, _csrf: Mutation
) -> WorkbenchView:
    actor = await administrator(request, db, write=True)
    result = await operations.update_metadata(workbench_id, body, request, db, actor)
    await db.commit()
    return result


@router.put("/{workbench_id}/scope", summary="更新工作台的组织使用范围")
async def update_scope(
    workbench_id: UUID, body: WorkbenchScope, request: Request, db: DB, _csrf: Mutation
) -> WorkbenchView:
    actor = await administrator(request, db, write=True)
    result = await operations.update_scope(workbench_id, body, request, db, actor)
    await db.commit()
    return result


@router.post(
    "/{workbench_id}/versions",
    status_code=201,
    summary="上传同一工作台的新版本草稿",
    openapi_extra=PACKAGE_BODY,
)
async def upload_version(
    workbench_id: UUID, request: Request, db: DB, _csrf: Mutation, revision: int = Query(ge=1)
) -> WorkbenchView:
    data, package = await upload(request, db)
    actor = await administrator(request, db, write=True)
    result = await operations.upload_version(
        workbench_id, request, db, actor, revision, data, package
    )
    await db.commit()
    return result


@router.put("/{workbench_id}/runtime-config", summary="保存工作台的组织运行配置")
async def update_runtime_config(
    workbench_id: UUID,
    body: WorkbenchConfigUpdate,
    request: Request,
    db: DB,
    _csrf: Mutation,
) -> WorkbenchView:
    actor = await administrator(request, db, write=True)
    result = await operations.update_runtime_config(workbench_id, body, request, db, actor)
    await db.commit()
    return result


@router.post("/{workbench_id}/versions/{version_id}/publish", summary="发布工作台草稿")
async def publish(
    workbench_id: UUID,
    version_id: UUID,
    body: WorkbenchPublish,
    request: Request,
    db: DB,
    _csrf: Mutation,
) -> WorkbenchView:
    actor = await administrator(request, db, write=True)
    result = await operations.publish(workbench_id, version_id, body, request, db, actor)
    await db.commit()
    return result


@router.post("/{workbench_id}/versions/{version_id}/withdraw", summary="下架当前发布版本")
async def withdraw(
    workbench_id: UUID,
    version_id: UUID,
    body: WorkbenchRevision,
    request: Request,
    db: DB,
    _csrf: Mutation,
) -> WorkbenchView:
    actor = await administrator(request, db, write=True)
    result = await operations.withdraw(workbench_id, version_id, body, request, db, actor)
    await db.commit()
    return result


@router.delete("/{workbench_id}/versions/{version_id}", summary="删除未发布的版本草稿")
async def delete_draft(
    workbench_id: UUID,
    version_id: UUID,
    request: Request,
    db: DB,
    _csrf: Mutation,
    revision: int = Query(ge=1),
) -> Message:
    actor = await administrator(request, db, write=True)
    result = await operations.delete_draft(workbench_id, version_id, request, db, actor, revision)
    await db.commit()
    return result
