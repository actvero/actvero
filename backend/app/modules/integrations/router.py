import secrets
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPBearer
from sqlalchemy import func, select

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, digest, now, provider
from app.modules.desktop.errors import fail
from app.modules.integrations import catalog, knowledge, service
from app.modules.integrations.models import IntegrationApplication, IntegrationKey
from app.modules.integrations.schemas import (
    ApplicationCallStatus,
    ApplicationConnection,
    ApplicationCreate,
    ApplicationKeyCreate,
    ApplicationKeyCreated,
    ApplicationKeyView,
    ApplicationPage,
    ApplicationUpdate,
    ApplicationView,
)
from app.modules.llm.call_queries import CallFilters, call_page
from app.modules.llm.call_schemas import CallPage
from app.modules.llm.models import ModelCall, UsageSettlement
from app.modules.members.service import Access, record

router = APIRouter(prefix="/api/v1/integrations", tags=["application-integrations"])
bearer = HTTPBearer(scheme_name="ApplicationKey", description="组织应用集成签发的 avi_ 密钥。")
public = APIRouter(prefix="/api/integrations/v1", dependencies=[Depends(bearer)])
public.include_router(catalog.router)
public.include_router(knowledge.router)


async def administrator(request: Request, db: DB, *, write: bool = False) -> Access:
    actor = await own_access(request, db, write=write, allow_platform_elevation=False)
    if actor.member.role != "administrator":
        fail(403, "administrator_required", "仅组织管理员可以管理应用集成")
    return actor


def endpoint(request: Request) -> str:
    return provider(request).settings.app_url.rstrip("/") + "/api/llm/v1"


def capabilities(app: IntegrationApplication | ApplicationCreate) -> dict[str, bool]:
    return {f"{key}_enabled": getattr(app, f"{key}_enabled") for key in service.CAPABILITIES}


def view(
    app: IntegrationApplication, request: Request, last_used_at: datetime | None = None
) -> ApplicationView:
    return ApplicationView(
        id=app.id,
        name=app.name,
        enabled=app.enabled,
        version=app.version,
        **capabilities(app),
        created_at=app.created_at,
        last_used_at=last_used_at,
        model_base_url=endpoint(request),
        integration_base_url=provider(request).settings.app_url.rstrip("/")
        + "/api/integrations/v1",
    )


async def application(db: DB, actor: Access, app_id: UUID) -> IntegrationApplication:
    row = await db.get(IntegrationApplication, app_id, populate_existing=True)
    if row is None or row.tenant_id != actor.tenant.id:
        fail(404, "application_not_found", "应用不存在")
    return row


async def validate(
    db: DB,
    actor: Access,
    body: ApplicationCreate,
    app_id: UUID,
) -> None:
    tenant_id = actor.tenant.id
    duplicate = await db.scalar(
        select(IntegrationApplication.id).where(
            IntegrationApplication.tenant_id == tenant_id,
            IntegrationApplication.name == body.name,
            IntegrationApplication.id != app_id,
        )
    )
    if duplicate:
        fail(409, "application_name_exists", "应用名称已存在")


@router.get("/applications", response_model=ApplicationPage)
async def applications(request: Request, db: DB, page: int = Query(1, ge=1)) -> ApplicationPage:
    actor = await administrator(request, db)
    scope = IntegrationApplication.tenant_id == actor.tenant.id
    used = (
        select(func.max(IntegrationKey.last_used_at))
        .where(IntegrationKey.application_id == IntegrationApplication.id)
        .scalar_subquery()
    )
    rows = await db.execute(
        select(IntegrationApplication, used)
        .where(scope)
        .order_by(IntegrationApplication.created_at.desc(), IntegrationApplication.id)
        .limit(20)
        .offset((page - 1) * 20)
    )
    return ApplicationPage(
        items=[view(app, request, stamp) for app, stamp in rows],
        total=await db.scalar(select(func.count(IntegrationApplication.id)).where(scope)) or 0,
    )


@router.post("/applications", response_model=ApplicationView, status_code=201)
async def create(body: ApplicationCreate, request: Request, db: DB, _: Mutation) -> ApplicationView:
    actor = await administrator(request, db, write=True)
    app_id = uuid4()
    await validate(db, actor, body, app_id)
    row = IntegrationApplication(
        id=app_id,
        tenant_id=actor.tenant.id,
        name=body.name,
        **capabilities(body),
    )
    db.add(row)
    record(db, actor, "integration.application.create", row.id, row.name)
    await db.commit()
    return view(row, request)


@router.get("/applications/{app_id}", response_model=ApplicationView)
async def detail(app_id: UUID, request: Request, db: DB) -> ApplicationView:
    row = await application(db, await administrator(request, db), app_id)
    return view(
        row,
        request,
        await db.scalar(
            select(func.max(IntegrationKey.last_used_at)).where(
                IntegrationKey.application_id == app_id
            )
        ),
    )


@router.put("/applications/{app_id}", response_model=ApplicationView)
async def update(
    app_id: UUID, body: ApplicationUpdate, request: Request, db: DB, _: Mutation
) -> ApplicationView:
    actor = await administrator(request, db, write=True)
    row = await application(db, actor, app_id)
    if body.version != row.version:
        fail(409, "application_changed", "应用已被修改，请刷新后重试")
    await validate(db, actor, body, app_id)
    old_enabled = row.enabled
    row.name = body.name
    row.enabled = body.enabled
    for field, enabled in capabilities(body).items():
        if field in body.model_fields_set:
            setattr(row, field, enabled)
    row.version += 1
    action = "update" if old_enabled == row.enabled else "enable" if row.enabled else "disable"
    record(
        db,
        actor,
        "integration.application." + action,
        row.id,
        row.name,
        {field: str(enabled).lower() for field, enabled in capabilities(row).items()},
    )
    await db.commit()
    return view(row, request)


def key_view(row: IntegrationKey) -> ApplicationKeyView:
    return ApplicationKeyView(
        id=row.id,
        name=row.name,
        hint=row.hint,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
        status="revoked" if row.revoked_at else "expired" if row.expires_at <= now() else "active",
    )


@router.get("/applications/{app_id}/keys", response_model=list[ApplicationKeyView])
async def keys(app_id: UUID, request: Request, db: DB) -> list[ApplicationKeyView]:
    await application(db, await administrator(request, db), app_id)
    rows = await db.scalars(
        select(IntegrationKey)
        .where(IntegrationKey.application_id == app_id)
        .order_by(IntegrationKey.created_at.desc(), IntegrationKey.id)
    )
    return [key_view(row) for row in rows]


@router.post("/applications/{app_id}/keys", response_model=ApplicationKeyCreated, status_code=201)
async def create_key(
    app_id: UUID,
    body: ApplicationKeyCreate,
    request: Request,
    response: Response,
    db: DB,
    _: Mutation,
) -> ApplicationKeyCreated:
    actor = await administrator(request, db, write=True)
    app = await application(db, actor, app_id)
    if not app.enabled:
        fail(409, "application_disabled", "请先启用应用")
    stamp = now()
    count = await db.scalar(
        select(func.count(IntegrationKey.id)).where(
            IntegrationKey.application_id == app_id,
            IntegrationKey.revoked_at.is_(None),
            IntegrationKey.expires_at > stamp,
        )
    )
    if count is not None and count >= 10:
        fail(409, "application_key_limit", "每个应用最多有 10 个有效密钥")
    secret = service.KEY_PREFIX + secrets.token_urlsafe(32)
    row = IntegrationKey(
        application_id=app.id,
        name=body.name,
        token_hash=digest(secret),
        hint=secret[:8] + "…" + secret[-4:],
        created_at=stamp,
        expires_at=stamp + timedelta(days=body.days),
    )
    db.add(row)
    await db.flush()
    record(db, actor, "integration.key.create", row.id, app.name, {"name": row.name})
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return ApplicationKeyCreated(key=key_view(row), secret=secret)


@router.delete("/applications/{app_id}/keys/{key_id}", status_code=204)
async def revoke_key(app_id: UUID, key_id: UUID, request: Request, db: DB, _: Mutation) -> Response:
    actor = await administrator(request, db, write=True)
    app = await application(db, actor, app_id)
    row = await db.get(IntegrationKey, key_id, populate_existing=True)
    if row is None or row.application_id != app.id:
        fail(404, "application_key_not_found", "应用密钥不存在")
    if not row.revoked_at:
        row.revoked_at = now()
        record(db, actor, "integration.key.revoke", row.id, app.name, {"name": row.name})
        await db.commit()
    return Response(status_code=204)


@router.get("/applications/{app_id}/calls", response_model=CallPage)
async def calls(app_id: UUID, request: Request, db: DB, page: int = Query(1, ge=1)) -> CallPage:
    actor = await administrator(request, db)
    await application(db, actor, app_id)
    return await call_page(db, CallFilters(actor.tenant.id, application_id=app_id), page)


@public.get(
    "/me",
    response_model=ApplicationConnection,
    tags=["application-api"],
    summary="测试应用密钥并获取能力开关与服务地址",
)
async def me(request: Request, response: Response, db: DB) -> ApplicationConnection:
    actor = await service.authorize(request, db)
    actor.key.last_used_at = now()
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return ApplicationConnection(
        application_id=actor.application.id,
        name=actor.application.name,
        model_base_url=endpoint(request),
        integration_base_url=provider(request).settings.app_url.rstrip("/")
        + "/api/integrations/v1",
        **capabilities(actor.application),
    )


@public.get(
    "/calls/{call_id}",
    response_model=ApplicationCallStatus,
    tags=["application-api"],
    summary="查询本应用模型调用回执",
)
async def call_status(call_id: UUID, request: Request, db: DB) -> ApplicationCallStatus:
    actor = await service.authorize(request, db)
    log = await db.get(ModelCall, call_id)
    if (
        log is None
        or log.tenant_id != actor.tenant.id
        or log.application_id != actor.application.id
    ):
        fail(404, "call_not_found", "调用记录不存在")
    usage = await db.get(UsageSettlement, call_id)
    return ApplicationCallStatus(
        id=call_id, status=log.status, settlement_status=usage.status if usage else "unknown"
    )
