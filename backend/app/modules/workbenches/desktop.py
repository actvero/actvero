"""Distribute published workbenches and resolve configuration for authorized versions."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPBearer
from sqlalchemy import ColumnElement, or_, select, true
from sqlalchemy.orm import aliased

from app.modules.auth.service import DB
from app.modules.desktop.errors import fail
from app.modules.desktop.resources import WORKBENCH_CONFIG, NativeActor, authorize
from app.modules.desktop.schemas import DesktopErrorResponse
from app.modules.workbenches.configuration import parse_fields, resolve
from app.modules.workbenches.models import Workbench, WorkbenchPackage, WorkbenchVersion
from app.modules.workbenches.schemas import (
    DesktopWorkbenchCatalog,
    DesktopWorkbenchCheck,
    DesktopWorkbenchPin,
    DesktopWorkbenchRelease,
    WorkbenchConfigRequest,
    WorkbenchRuntimeConfig,
)

router = APIRouter(
    prefix="/api/v1/desktop/workbenches",
    tags=["desktop-workbenches"],
    dependencies=[
        Depends(
            HTTPBearer(
                scheme_name="WorkbenchConfigResource",
                auto_error=False,
                description="使用 workbenches:config 资源令牌。",
            )
        )
    ],
    responses={code: {"model": DesktopErrorResponse} for code in (401, 403, 404, 409, 503)},
)


def visible(actor: NativeActor) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    audience = (
        true()
        if actor.member.role == "administrator"
        else or_(
            Workbench.audience == "organization",
            (Workbench.audience == "selected")
            & Workbench.member_ids.contains([str(actor.member.id)]),
        )
    )
    return (Workbench.tenant_id == actor.tenant.id, audience)


@router.get("", summary="列出当前成员可使用的工作台")
async def catalog(request: Request, db: DB) -> DesktopWorkbenchCatalog:
    actor = await authorize(request, db, WORKBENCH_CONFIG)
    rows = await db.execute(
        select(Workbench, WorkbenchVersion)
        .join(WorkbenchVersion, WorkbenchVersion.workbench_id == Workbench.id)
        .where(*visible(actor), WorkbenchVersion.status == "published")
        .order_by(Workbench.display_name, Workbench.id)
    )
    return DesktopWorkbenchCatalog(
        items=[
            DesktopWorkbenchRelease(
                workbench_id=row.id,
                version_id=version.id,
                package_name=row.package_name,
                display_name=row.display_name,
                description=row.description,
                category=row.category,
                version=version.version,
                dsh_requirement=version.dsh_requirement,
                size=version.size,
                sha256=version.sha256,
            )
            for row, version in rows
        ]
    )


@router.post("/check-updates", summary="检查已安装版本的使用权限和更新")
async def check_updates(
    request: Request, db: DB, body: DesktopWorkbenchPin
) -> DesktopWorkbenchCheck:
    actor = await authorize(request, db, WORKBENCH_CONFIG)
    adopted = aliased(WorkbenchVersion)
    result = (
        await db.execute(
            select(WorkbenchVersion.id, adopted.id.label("adopted_id"))
            .join(Workbench, Workbench.id == WorkbenchVersion.workbench_id)
            .outerjoin(
                adopted,
                (adopted.workbench_id == Workbench.id)
                & (adopted.id == body.version_id)
                & (adopted.sha256 == body.sha256)
                & adopted.status.in_(("published", "superseded")),
            )
            .where(
                *visible(actor),
                Workbench.id == body.workbench_id,
                WorkbenchVersion.status == "published",
            )
        )
    ).one_or_none()
    if result is None:
        return DesktopWorkbenchCheck(status="unavailable", adopted_usable=False)
    return DesktopWorkbenchCheck(
        status="current" if result.id == result.adopted_id else "update_available",
        adopted_usable=result.adopted_id is not None,
    )


@router.post(
    "/download",
    response_class=Response,
    summary="核对成员权限和发布版本摘要后发放工作台安装包",
    responses={
        200: {"content": {"application/gzip": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def download(request: Request, db: DB, body: DesktopWorkbenchPin) -> Response:
    actor = await authorize(request, db, WORKBENCH_CONFIG, write=True)
    current = await db.scalar(
        select(WorkbenchVersion)
        .join(Workbench, Workbench.id == WorkbenchVersion.workbench_id)
        .where(
            *visible(actor),
            Workbench.id == body.workbench_id,
            WorkbenchVersion.status == "published",
        )
    )
    if current is None:
        fail(404, "workbench_unavailable", "当前组织没有可用的工作台版本")
    if current.id != body.version_id or current.sha256 != body.sha256:
        fail(409, "workbench_version_changed", "工作台发布版本已变化，请刷新后重试")
    package = await db.get(WorkbenchPackage, current.id)
    if package is None:
        fail(404, "workbench_unavailable", "工作台安装包不可用")
    return Response(
        package.data, media_type="application/gzip", headers={"Cache-Control": "no-store"}
    )


@router.post("/config", summary="读取当前成员获准的工作台版本运行配置")
async def runtime_config(
    request: Request, db: DB, body: WorkbenchConfigRequest
) -> WorkbenchRuntimeConfig:
    actor = await authorize(request, db, WORKBENCH_CONFIG)
    current = aliased(WorkbenchVersion)
    active = (
        select(current.id)
        .where(current.workbench_id == Workbench.id, current.status == "published")
        .exists()
    )
    conditions = [
        *visible(actor),
        Workbench.package_name == body.package_name,
        WorkbenchVersion.version == body.version,
        WorkbenchVersion.status.in_(("published", "superseded")),
        active,
    ]
    result = (
        await db.execute(
            select(Workbench.config_values, WorkbenchVersion.config_fields)
            .join(WorkbenchVersion, WorkbenchVersion.workbench_id == Workbench.id)
            .where(*conditions)
        )
    ).one_or_none()
    if result is None:
        fail(404, "workbench_unavailable", "当前组织没有可用的工作台版本")
    try:
        return WorkbenchRuntimeConfig(
            values=resolve(parse_fields(result.config_fields), result.config_values)
        )
    except ValueError:
        fail(409, "workbench_config_incomplete", "请联系管理员补全工作台运行配置")
