from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, now
from app.modules.members.models import Membership
from app.modules.members.service import Access, record
from app.modules.workbenches.configuration import parse_fields, resolve, validate_value
from app.modules.workbenches.models import Workbench, WorkbenchPackage, WorkbenchVersion
from app.modules.workbenches.packages import MAX_PACKAGE_BYTES, Package, inspect, version_order
from app.modules.workbenches.schemas import (
    WorkbenchCategory,
    WorkbenchConfigUpdate,
    WorkbenchMetadata,
    WorkbenchPage,
    WorkbenchPublish,
    WorkbenchRevision,
    WorkbenchScope,
    WorkbenchStatus,
    WorkbenchSummary,
    WorkbenchVersionView,
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
    if request.headers.get("content-type", "").split(";", 1)[0] not in {
        "application/octet-stream",
        "application/gzip",
        "application/x-gzip",
    }:
        raise HTTPException(415, "请选择 .tgz 工作台安装包")
    buffer = bytearray()
    async for chunk in request.stream():
        if len(buffer) + len(chunk) > MAX_PACKAGE_BYTES:
            raise HTTPException(413, "工作台包不能超过 8 MiB")
        buffer.extend(chunk)
    data = bytes(buffer)
    try:
        return data, await run_in_threadpool(inspect, data)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


async def get_workbench(
    db: AsyncSession, actor: Access, workbench_id: UUID, revision: int | None = None
) -> Workbench:
    row = await db.scalar(
        select(Workbench).where(
            Workbench.id == workbench_id, Workbench.tenant_id == actor.tenant.id
        )
    )
    if row is None:
        raise HTTPException(404, "工作台不存在")
    if revision is not None and row.revision != revision:
        raise HTTPException(409, "工作台已被修改，请刷新后重试")
    return row


async def versions(db: AsyncSession, row: Workbench) -> list[WorkbenchVersion]:
    return list(
        await db.scalars(
            select(WorkbenchVersion)
            .where(WorkbenchVersion.workbench_id == row.id)
            .order_by(WorkbenchVersion.created_at.desc(), WorkbenchVersion.id)
        )
    )


def summary(
    row: Workbench, current: str | None, has_draft: bool, was_published: bool, icon: str | None
) -> WorkbenchSummary:
    return WorkbenchSummary.model_validate(
        {
            "id": row.id,
            "package_name": row.package_name,
            "display_name": row.display_name,
            "description": row.description,
            "icon_data_url": icon,
            "category": row.category,
            "audience": row.audience,
            "updated_at": row.updated_at,
            "current_version": current,
            "status": "published" if current else "withdrawn" if was_published else "draft",
            "has_draft": has_draft,
        }
    )


async def view(db: AsyncSession, row: Workbench) -> WorkbenchView:
    releases = await versions(db, row)
    current = next((item for item in releases if item.status == "published"), None)
    display = current or next(iter(releases), None)
    return WorkbenchView(
        **summary(
            row,
            current.version if current else None,
            any(item.status == "draft" for item in releases),
            any(item.published_at is not None for item in releases),
            display.icon_data_url if display else None,
        ).model_dump(),
        revision=row.revision,
        member_ids=[UUID(ident) for ident in row.member_ids],
        config_values=row.config_values,
        versions=[WorkbenchVersionView.model_validate(item) for item in releases],
    )


def changed(row: Workbench) -> None:
    row.revision += 1
    row.updated_at = now()


def newer_than_published(package_version: str, releases: list[WorkbenchVersion]) -> None:
    candidate = version_order(package_version)
    if any(item.published_at and candidate <= version_order(item.version) for item in releases):
        raise HTTPException(409, "新版本必须高于所有已发布版本")


async def add_version(
    db: AsyncSession, actor: Access, row: Workbench, package: Package, data: bytes
) -> None:
    version = WorkbenchVersion(
        workbench_id=row.id,
        version=package.version,
        dsh_requirement=package.dsh_requirement,
        size=len(data),
        sha256=package.sha256,
        uploader_name=actor.user.name,
        config_fields=[field.model_dump() for field in package.config_fields],
        icon_data_url=package.icon_data_url,
    )
    db.add(version)
    await db.flush()
    db.add(WorkbenchPackage(version_id=version.id, data=data))
    record(db, actor, "workbench.upload", row.id, row.display_name, {"version": version.version})


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
    query = select(WorkbenchVersion).where(WorkbenchVersion.workbench_id == Workbench.id)
    current = (
        query.with_only_columns(WorkbenchVersion.version)
        .where(WorkbenchVersion.status == "published")
        .scalar_subquery()
    )
    drafts = query.where(WorkbenchVersion.status == "draft").exists()
    published = query.where(WorkbenchVersion.published_at.is_not(None)).exists()
    icon = (
        query.with_only_columns(WorkbenchVersion.icon_data_url)
        .order_by(
            (WorkbenchVersion.status == "published").desc(),
            WorkbenchVersion.created_at.desc(),
            WorkbenchVersion.id,
        )
        .limit(1)
        .scalar_subquery()
    )
    filters = [Workbench.tenant_id == actor.tenant.id]
    if q.strip():
        filters.append(
            or_(
                Workbench.display_name.icontains(q.strip(), autoescape=True),
                Workbench.package_name.icontains(q.strip(), autoescape=True),
            )
        )
    if category is not None:
        filters.append(Workbench.category == category)
    if status == "published":
        filters.append(current.is_not(None))
    elif status == "withdrawn":
        filters.extend([current.is_(None), published])
    elif status == "draft":
        filters.append(~published)
    total = await db.scalar(select(func.count()).select_from(Workbench).where(*filters))
    rows = await db.execute(
        select(Workbench, current, drafts, published, icon)
        .where(*filters)
        .order_by(Workbench.updated_at.desc(), Workbench.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    return WorkbenchPage(items=[summary(*item) for item in rows.tuples()], total=total or 0)


@router.post("", status_code=201, summary="上传工作台并创建草稿", openapi_extra=PACKAGE_BODY)
async def create_workbench(request: Request, db: DB, _csrf: Mutation) -> WorkbenchView:
    data, package = await upload(request, db)
    actor = await administrator(request, db, write=True)
    if await db.scalar(
        select(Workbench.id).where(
            Workbench.tenant_id == actor.tenant.id, Workbench.package_name == package.name
        )
    ):
        raise HTTPException(409, "此包名已存在，请从工作台详情上传新版本")
    row = Workbench(
        tenant_id=actor.tenant.id,
        package_name=package.name,
        display_name=package.display_name,
        description=package.description,
    )
    db.add(row)
    await db.flush()
    await add_version(db, actor, row, package, data)
    result = await view(db, row)
    await db.commit()
    return result


@router.get("/{workbench_id}", summary="查看工作台资料和版本历史")
async def detail(workbench_id: UUID, request: Request, db: DB) -> WorkbenchView:
    actor = await administrator(request, db)
    return await view(db, await get_workbench(db, actor, workbench_id))


@router.put("/{workbench_id}", summary="更新工作台展示资料")
async def update_metadata(
    workbench_id: UUID, body: WorkbenchMetadata, request: Request, db: DB, _csrf: Mutation
) -> WorkbenchView:
    actor = await administrator(request, db, write=True)
    row = await get_workbench(db, actor, workbench_id, body.revision)
    row.display_name, row.description, row.category = (
        body.display_name,
        body.description,
        body.category,
    )
    changed(row)
    record(db, actor, "workbench.metadata", row.id, row.display_name)
    result = await view(db, row)
    await db.commit()
    return result


@router.put("/{workbench_id}/scope", summary="更新工作台的组织使用范围")
async def update_scope(
    workbench_id: UUID, body: WorkbenchScope, request: Request, db: DB, _csrf: Mutation
) -> WorkbenchView:
    actor = await administrator(request, db, write=True)
    row = await get_workbench(db, actor, workbench_id, body.revision)
    if body.member_ids:
        valid = set(
            await db.scalars(
                select(Membership.id).where(
                    Membership.tenant_id == actor.tenant.id,
                    Membership.status == "active",
                    Membership.source != "platform",
                    Membership.id.in_(body.member_ids),
                )
            )
        )
        if valid != set(body.member_ids):
            raise HTTPException(422, "请选择当前组织的有效成员")
    row.audience = body.audience
    row.member_ids = [str(ident) for ident in body.member_ids]
    changed(row)
    record(db, actor, "workbench.scope", row.id, row.display_name, {"audience": row.audience})
    result = await view(db, row)
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
    row = await get_workbench(db, actor, workbench_id, revision)
    if row.package_name != package.name:
        raise HTTPException(422, "新版本的包名必须和原工作台一致")
    releases = await versions(db, row)
    if any(item.version == package.version for item in releases):
        raise HTTPException(409, "此版本号已存在")
    newer_than_published(package.version, releases)
    await add_version(db, actor, row, package, data)
    changed(row)
    result = await view(db, row)
    await db.commit()
    return result


def find_version(releases: list[WorkbenchVersion], version_id: UUID) -> WorkbenchVersion:
    version = next((item for item in releases if item.id == version_id), None)
    if version is None:
        raise HTTPException(404, "工作台版本不存在")
    return version


@router.put("/{workbench_id}/runtime-config", summary="保存工作台的组织运行配置")
async def update_runtime_config(
    workbench_id: UUID,
    body: WorkbenchConfigUpdate,
    request: Request,
    db: DB,
    _csrf: Mutation,
) -> WorkbenchView:
    actor = await administrator(request, db, write=True)
    row = await get_workbench(db, actor, workbench_id, body.revision)
    releases = await versions(db, row)
    version = find_version(releases, body.version_id)
    if version.status == "withdrawn":
        raise HTTPException(409, "已下架版本的配置仅供查看")
    fields = {field.key: field for field in parse_fields(version.config_fields)}
    if not body.values.keys() <= fields.keys():
        raise HTTPException(422, "只能填写该版本声明的运行配置")

    values = {key: value for key, value in row.config_values.items() if key not in fields}
    try:
        for key, raw in body.values.items():
            value = raw.strip()
            if value:
                validate_value(fields[key], value)
                values[key] = value
        for release in releases:
            if release.status in {"published", "superseded"}:
                resolve(parse_fields(release.config_fields), values)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None

    row.config_values = values
    changed(row)
    record(
        db,
        actor,
        "workbench.runtime_config",
        row.id,
        row.display_name,
        {"version": version.version},
    )
    result = await view(db, row)
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
    row = await get_workbench(db, actor, workbench_id, body.revision)
    releases = await versions(db, row)
    version = find_version(releases, version_id)
    if version.status != "draft":
        raise HTTPException(409, "仅草稿可以发布")
    newer_than_published(version.version, releases)
    try:
        resolve(parse_fields(version.config_fields), row.config_values)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
    for item in releases:
        if item.status == "published":
            item.status = "superseded"
    await db.flush()
    version.status, version.published_at = "published", now()
    version.release_notes = body.release_notes
    changed(row)
    record(db, actor, "workbench.publish", row.id, row.display_name, {"version": version.version})
    result = await view(db, row)
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
    row = await get_workbench(db, actor, workbench_id, body.revision)
    version = find_version(await versions(db, row), version_id)
    if version.status != "published":
        raise HTTPException(409, "仅当前发布版本可以下架")
    version.status = "withdrawn"
    changed(row)
    record(db, actor, "workbench.withdraw", row.id, row.display_name, {"version": version.version})
    result = await view(db, row)
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
    row = await get_workbench(db, actor, workbench_id, revision)
    version = find_version(await versions(db, row), version_id)
    if version.status != "draft":
        raise HTTPException(409, "仅未发布的草稿可以删除")
    await db.delete(version)
    changed(row)
    record(
        db, actor, "workbench.delete_draft", row.id, row.display_name, {"version": version.version}
    )
    await db.commit()
    return Message(message="已删除草稿")
