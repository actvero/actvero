from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, now, provider
from app.modules.llm.channel_address_schemas import ChannelAddressInput
from app.modules.llm.channel_inventory import (
    assert_inventory_removable,
    project_binding_references,
    project_latest_diagnostics,
)
from app.modules.llm.channel_management import (
    default_status,
    effective_connection,
    execution_address_signature,
    receipt_digest,
    stored_connection_view,
    stored_defaults,
    validate_registered_targets,
)
from app.modules.llm.diagnostic_schemas import DiagnosticDetail, DiagnosticRequest
from app.modules.llm.models import ModelChannel, MutationReceipt
from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.base import ModelListing
from app.modules.llm.providers.connection import ResolvedConnection, resolve_connection
from app.modules.llm.schemas import (
    ArchiveInput,
    ChannelChatProbe,
    ChannelDetail,
    ChannelHealthSummary,
    ChannelInput,
    ChannelPage,
    ChannelProbe,
    ChannelRemovalConflictResponse,
    ChannelStatusBatch,
    ChannelStatusBatchResult,
    ChannelStatusInput,
    ChannelStatusResult,
    ChannelTestInput,
    ChannelTestRecord,
    ChannelTestView,
    ChannelUpdate,
    ChannelView,
    CheckRecord,
    ConnectionInput,
    DiscoveryView,
    DraftInspectionInput,
    DraftInspectionView,
    ModelDirectory,
    ModelHint,
    ModelsInput,
    MutationReceiptView,
    ProtectionSettings,
    ProviderView,
    RegisteredModel,
    UpstreamModel,
    Version,
)
from app.modules.mcp.schemas import normalize_icon
from app.modules.members.service import Access, BusinessActor, record

router = APIRouter(prefix="/api/v1/llm", tags=["llm-channels"])


@router.get("/channels/{channel_id}/model-hint", response_model=ModelHint)
async def upstream_model_hint(
    request: Request, db: DB, channel_id: UUID, model_id: str = Query(max_length=200)
) -> ModelHint:
    from app.modules.llm.providers.model_hints import model_hint

    actor = await administrator(request, db)
    row = await channel(db, actor, channel_id)
    editable(row)
    if not any(model["id"] == model_id for model in row.models):
        raise HTTPException(404, "上游模型未登记")
    return model_hint(row.provider, model_id, row.declared_apis)


async def administrator(request: Request, db: DB, *, write: bool = False) -> Access:
    actor = await own_access(request, db, write=write)
    if actor.member.role != "administrator":
        raise HTTPException(403, "仅管理员可以管理模型渠道")
    return actor


async def channel(
    db: DB, actor: BusinessActor, channel_id: UUID, version: int | None = None
) -> ModelChannel:
    row = await db.scalar(
        select(ModelChannel)
        .where(ModelChannel.id == channel_id, ModelChannel.tenant_id == actor.tenant.id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "渠道不存在")
    if version is not None and row.version != version:
        raise HTTPException(409, "渠道已被修改，请刷新后重试")
    return row


def editable(row: ModelChannel) -> None:
    if (row.routing or {}).get("engine") == "newapi":
        raise HTTPException(409, "这是受管网关连接，请通过部署配置维护")
    if row.archived:
        raise HTTPException(409, "请先恢复已归档渠道")


def connection_key(
    request: Request,
    body: ConnectionInput,
    row: ModelChannel | None,
    *,
    address_changed: bool = False,
) -> str | None:
    if body.auth_mode == "none":
        return None
    if body.api_key is not None:
        key = body.api_key.get_secret_value()
        # Format only: an sk-sp- prefix is not proof of validity or entitlement.
        # Keep these errors after auth and return a safe, actionable message.
        if body.provider == "qwen-token-plan" and not key.startswith("sk-sp-"):
            raise HTTPException(422, "千问 Token Plan 请使用 sk-sp- 开头的套餐专属 API Key")
        if body.provider == "qwen" and key.startswith("sk-sp-"):
            raise HTTPException(422, "这是套餐 API Key，请选择千问 Token Plan 渠道")
        return key
    if (
        row is None
        or not row.sealed_key
        or address_changed
        or body.base_url != row.base_url
        and body.connection is None
        or body.provider != row.provider
    ):
        raise HTTPException(422, "请填写 API Key；修改地址时须重新提供密钥")
    return str(provider(request).unseal(row.sealed_key)["key"])


def directory_view(row: ModelChannel) -> ModelDirectory | None:
    if row.snapshot_id is None or row.snapshot_at is None:
        return None
    return ModelDirectory(
        snapshot_id=row.snapshot_id,
        fetched_at=row.snapshot_at,
        candidates=[UpstreamModel(id=model_id) for model_id in row.snapshot],
        partial=row.snapshot_partial,
    )


def cache_directory(row: ModelChannel, listing: ModelListing) -> None:
    row.snapshot_id = uuid4()
    row.snapshot_at = now()
    row.snapshot = [model.id for model in listing.models]
    row.snapshot_partial = listing.partial


def view(row: ModelChannel, health_summary: ChannelHealthSummary | None = None) -> ChannelDetail:
    defaults = stored_defaults(row)
    return ChannelDetail(
        **{
            name: getattr(row, name)
            for name in (
                "id",
                "version",
                "provider",
                "name",
                "description",
                "icon",
                "base_url",
                "auth_mode",
                "timeout_seconds",
                "declared_apis",
                "archived",
                "created_at",
            )
        },
        credential_configured=bool(row.sealed_key),
        connection=stored_connection_view(row),
        manual_enabled=row.manual_enabled,
        automatic_protection=ProtectionSettings.model_validate(
            row.automatic_protection or {"enabled": True}
        ),
        test_defaults=defaults,
        test_defaults_status=default_status(
            defaults,
            provider_id=row.provider,
            declared_apis=row.declared_apis,
            models=row.models or [],
        ),
        routing_version=row.routing_version,
        health_summary=health_summary,
        model_count=len(row.models),
        last_check=CheckRecord.model_validate(row.checks[0]) if row.checks else None,
        models=[RegisteredModel.model_validate(m) for m in row.models],
        checks=[CheckRecord.model_validate(c) for c in row.checks],
        model_directory=directory_view(row),
    )


async def configure(
    request: Request, db: DB, actor: Access, body: ChannelInput, row: ModelChannel
) -> None:
    provided = body.model_fields_set.copy()
    if row.provider is not None:
        inherited = {
            field: getattr(row, field)
            for field in (
                "provider",
                "base_url",
                "auth_mode",
                "timeout_seconds",
                "declared_apis",
                "name",
                "description",
                "icon",
            )
            if field not in provided
        }
        if inherited:
            body = body.model_copy(update=inherited)
    if row.provider is not None and body.provider != row.provider:
        raise HTTPException(422, "已有渠道不能更换供应商，请创建新渠道以保留原调用关联")
    if not body.name:
        raise HTTPException(422, "请填写渠道名称")
    duplicate = await db.scalar(
        select(ModelChannel.id).where(
            ModelChannel.tenant_id == actor.tenant.id,
            ModelChannel.name == body.name,
            ModelChannel.id != row.id,
        )
    )
    if duplicate:
        raise HTTPException(409, "已存在同名渠道（包括已归档渠道）")
    effective_base, connection = effective_connection(body, row if row.provider else None, provided)
    existing_channel = row.provider is not None
    old_routing_version = (row.routing_version or row.version) if existing_channel else 1
    old_address = (
        execution_address_signature(row.provider, row.base_url, row.connection)
        if existing_channel
        else None
    )
    address_changed = old_address is not None and old_address != execution_address_signature(
        body.provider, effective_base, connection
    )
    changed = bool(
        existing_channel
        and (
            address_changed
            or any(
                getattr(row, field) != getattr(body, field)
                for field in ("provider", "auth_mode", "timeout_seconds", "declared_apis")
            )
            or body.api_key is not None
        )
    )
    directory_changed = (
        address_changed or body.auth_mode != row.auth_mode or body.api_key is not None
    )
    key = connection_key(
        request, body, row if row.provider else None, address_changed=address_changed
    )
    if key is None:
        row.sealed_key = None
    elif body.api_key is not None:
        row.sealed_key = provider(request).seal({"key": key})
    row.provider = body.provider
    row.name = body.name
    row.description = body.description
    row.icon = normalize_icon(body.icon) if body.icon != row.icon else row.icon
    row.base_url = effective_base
    row.connection = connection
    row.auth_mode = body.auth_mode
    row.timeout_seconds = body.timeout_seconds
    row.declared_apis = [str(api) for api in body.declared_apis]
    row.routing_version = old_routing_version + int(changed)
    if "manual_enabled" in provided or row.manual_enabled is None:
        row.manual_enabled = body.manual_enabled
    if "automatic_protection" in provided or not row.automatic_protection:
        row.automatic_protection = body.automatic_protection.model_dump(mode="json")
    if body.models is not None:
        existing = {m["id"]: m for m in row.models or []}
        await assert_inventory_removable(db, row, set(existing) - {m.id for m in body.models})
        row.models = [
            existing.get(model_id)
            or RegisteredModel(id=model_id, source="configuration", registered_at=now()).model_dump(
                mode="json"
            )
            for model_id in dict.fromkeys(m.id for m in body.models)
        ]
    validate_registered_targets(row.provider, row.base_url, row.connection, row.models or [])
    if "test_defaults" in provided:
        status = default_status(
            body.test_defaults,
            provider_id=row.provider,
            declared_apis=row.declared_apis,
            models=row.models or [],
        )
        if status is not None and not status.valid:
            raise HTTPException(422, "默认测试模型、操作或接口不可用")
        row.test_defaults = (
            body.test_defaults.model_dump(mode="json") if body.test_defaults else None
        )
    if changed:
        row.checks = []
    if directory_changed:
        row.snapshot_id = None
        row.snapshot_at = None
        row.snapshot = []
        row.snapshot_partial = None


@router.get("/providers", response_model=list[ProviderView], summary="渠道厂商模块及能力")
async def providers(request: Request, db: DB) -> list[ProviderView]:
    await administrator(request, db)
    return [p.info for p in PROVIDERS.values()]


@router.post(
    "/channel-addresses/resolve",
    response_model=ResolvedConnection,
    summary="管理员预览有效地址，不保存或请求上游",
)
async def resolve_addresses(
    request: Request, db: DB, body: ChannelAddressInput, _csrf: Mutation
) -> ResolvedConnection:
    await administrator(request, db)
    try:
        return resolve_connection(
            body.provider,
            body.connection.connection(),
            model=body.model,
            operations=body.operations,
            stream=body.stream,
        )
    except ValueError as exc:
        # Invalid URLs can contain credentials. Never return the submitted value.
        raise HTTPException(422, "地址模式、接口前缀或供应商操作组合无效") from exc


@router.post(
    "/channel-drafts/inspect",
    response_model=DraftInspectionView,
    summary="读取连接的模型目录；连接未变更时缓存到已有渠道，不修改配置",
)
async def inspect_draft(
    request: Request, db: DB, body: DraftInspectionInput, _csrf: Mutation
) -> DraftInspectionView:
    actor = await administrator(request, db, write=True)
    row = None
    if body.channel_id is not None:
        row = await channel(db, actor, body.channel_id, body.version)
        editable(row)
        provided = body.model_fields_set.copy()
        inherited = {
            field: getattr(row, field)
            for field in ("provider", "base_url", "auth_mode", "timeout_seconds", "declared_apis")
            if field not in provided
        }
        if inherited:
            body = body.model_copy(update=inherited)
    else:
        provided = body.model_fields_set.copy()
    base, connection = effective_connection(body, row, provided)
    old_address = (
        execution_address_signature(row.provider, row.base_url, row.connection) if row else None
    )
    address_changed = bool(
        row and old_address != execution_address_signature(body.provider, base, connection)
    )
    key = connection_key(request, body, row, address_changed=address_changed)
    cacheable = bool(
        row
        and not address_changed
        and body.provider == row.provider
        and body.auth_mode == row.auth_mode
        and body.api_key is None
    )
    await db.commit()
    listing = None
    try:
        connection_kwargs = (
            {"connection": connection}
            if connection.get("address_mode") not in (None, "legacy_api_base")
            else {}
        )
        listing = await PROVIDERS[body.provider].list_models(
            base, key, body.timeout_seconds, provider(request).settings, **connection_kwargs
        )
        message = f"模型目录读取成功，返回 {len(listing.models)} 个模型"
    except HTTPException as exc:
        message = str(exc.detail)
    # Re-check authentication and optimistic version after external IO, without
    # keeping organization locks or temporary credentials in the database.
    actor = await administrator(request, db, write=True)
    if body.channel_id is not None:
        row = await channel(db, actor, body.channel_id, body.version)
        editable(row)
    if cacheable and row is not None and listing is not None and body.discover:
        cache_directory(row, listing)
    record(
        db,
        actor,
        "llm.channel.draft.discover" if body.discover else "llm.channel.draft.check",
        row.id if row is not None else actor.tenant.id,
        row.name if row is not None else "未保存渠道",
        result="success" if listing is not None else "failure",
    )
    result = DraftInspectionView(
        ok=listing is not None,
        message=message,
        checked_at=now(),
        candidates=listing.models if listing is not None and body.discover else [],
        partial=listing.partial if listing is not None else False,
        model_directory=directory_view(row) if cacheable and row is not None else None,
    )
    await db.commit()
    return result


@router.get("/channels", response_model=ChannelPage, summary="管理员渠道列表")
async def channels(
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=100),
    state: Literal["current", "archived", "all"] = "current",
    page: int = Query(default=1, ge=1),
    provider_id: str | None = Query(default=None, alias="provider"),
    manual_enabled: bool | None = None,
    health_summary: Literal[
        "not_applicable", "no_routes", "ready", "degraded", "unavailable", "unverified"
    ]
    | None = None,
) -> ChannelPage:
    actor = await administrator(request, db)
    return await channel_page(
        db,
        actor,
        q=q,
        state=state,
        page=page,
        provider_id=provider_id,
        manual_enabled=manual_enabled,
        health_summary=health_summary,
    )


async def channel_page(
    db: DB,
    actor: BusinessActor,
    *,
    q: str = "",
    state: str = "current",
    page: int = 1,
    provider_id: str | None = None,
    manual_enabled: bool | None = None,
    health_summary: str | None = None,
) -> ChannelPage:
    filters = [ModelChannel.tenant_id == actor.tenant.id]
    if state != "all":
        filters.append(ModelChannel.archived == (state == "archived"))
    if provider_id:
        filters.append(ModelChannel.provider == provider_id)
    if manual_enabled is not None:
        filters.append(ModelChannel.manual_enabled == manual_enabled)
    if q.strip():
        filters.append(
            or_(
                ModelChannel.name.icontains(q.strip(), autoescape=True),
                ModelChannel.base_url.icontains(q.strip(), autoescape=True),
            )
        )
    query = (
        select(ModelChannel)
        .where(*filters)
        .order_by(ModelChannel.created_at.desc(), ModelChannel.id)
    )
    if health_summary is None:
        total = await db.scalar(select(func.count()).select_from(ModelChannel).where(*filters))
        rows = list(await db.scalars(query.offset((page - 1) * 20).limit(20)))
    else:
        rows = list(await db.scalars(query))
    from app.modules.llm.channel_health import project_channel_health

    health = await project_channel_health(db, rows)
    if health_summary is not None:
        rows = [row for row in rows if health[row.id].state == health_summary]
        total = len(rows)
        rows = rows[(page - 1) * 20 : page * 20]
    diagnostics = await project_latest_diagnostics(db, rows)
    return ChannelPage(
        items=[
            ChannelView(
                **{
                    **view(row, health[row.id]).model_dump(),
                    "last_diagnostic": diagnostics.get(row.id),
                }
            )
            for row in rows
        ],
        total=total or 0,
    )


@router.post("/channels", response_model=ChannelDetail, summary="保存自定义渠道配置")
async def create(request: Request, db: DB, body: ChannelInput, _csrf: Mutation) -> ChannelDetail:
    actor = await administrator(request, db, write=True)
    signature = receipt_digest(request, body) if body.request_id else None
    if body.request_id:
        previous = await db.scalar(
            select(MutationReceipt).where(
                MutationReceipt.tenant_id == actor.tenant.id,
                MutationReceipt.actor_id == actor.user.id,
                MutationReceipt.scope == "channel.create",
                MutationReceipt.request_id == body.request_id,
            )
        )
        if previous:
            if previous.payload_digest != signature:
                raise HTTPException(409, "此请求标识已用于其他渠道配置")
            if previous.state != "completed":
                raise HTTPException(409, "渠道创建仍在处理，请稍后查询回执")
            existing = await channel(db, actor, previous.resource_id)
            return view(existing)
    if not PROVIDERS[body.provider].info.available_for_new_channels:
        raise HTTPException(422, "此供应商预设已停止新增，请选择其他供应商；已有渠道仍可编辑和调用")
    row = ModelChannel(id=uuid4(), tenant_id=actor.tenant.id)
    await configure(request, db, actor, body, row)
    db.add(row)
    await db.flush()
    record(db, actor, "llm.channel.create", row.id, row.name)
    if body.request_id:
        db.add(
            MutationReceipt(
                tenant_id=actor.tenant.id,
                actor_id=actor.user.id,
                scope="channel.create",
                request_id=body.request_id,
                payload_digest=signature,
                resource_id=row.id,
                state="completed",
            )
        )
    result = view(row)
    await db.commit()
    return result


@router.get("/channels/{channel_id}", response_model=ChannelDetail, summary="脱敏渠道详情")
async def detail(channel_id: UUID, request: Request, db: DB) -> ChannelDetail:
    actor = await administrator(request, db)
    return await channel_detail(db, actor, channel_id)


async def channel_detail(db: DB, actor: BusinessActor, channel_id: UUID) -> ChannelDetail:
    row = await channel(db, actor, channel_id)
    from app.modules.llm.channel_health import project_channel_health

    health = await project_channel_health(db, [row])
    result = view(row, health[row.id])
    result.binding_references = await project_binding_references(db, row)
    result.last_diagnostic = (await project_latest_diagnostics(db, [row])).get(row.id)
    return result


@router.get(
    "/mutation-receipts/{request_id}",
    response_model=MutationReceiptView,
    summary="管理员查询本人管理创建回执",
)
async def mutation_receipt(
    request_id: UUID,
    request: Request,
    db: DB,
    scope: str = Query(..., min_length=1, max_length=60),
) -> MutationReceiptView:
    actor = await administrator(request, db)
    if scope not in ("channel.create", "settlement.reconcile"):
        raise HTTPException(404, "管理回执不存在")
    row = await db.scalar(
        select(MutationReceipt).where(
            MutationReceipt.tenant_id == actor.tenant.id,
            MutationReceipt.actor_id == actor.user.id,
            MutationReceipt.scope == scope,
            MutationReceipt.request_id == request_id,
        )
    )
    if row is None:
        raise HTTPException(404, "管理回执不存在")
    if row.state != "completed":
        raise HTTPException(409, "请求仍在处理，请稍后查询")
    return MutationReceiptView(
        scope=scope,
        request_id=request_id,
        resource_id=row.resource_id,
        state="completed",
    )


@router.post(
    "/channels/{channel_id}/test/chat",
    response_model=ChannelTestView,
    summary="管理员指定渠道对话测试，不开放模型或变更成员额度",
)
async def test_channel_chat(
    channel_id: UUID,
    request: Request,
    db: DB,
    body: ChannelTestInput,
    _csrf: Mutation,
) -> ChannelTestView:
    from app.modules.llm.channel_testing import run

    return await run(
        channel_id, request, db, ChannelChatProbe(operation="chat", **body.model_dump())
    )


@router.post("/channels/{channel_id}/test", response_model=ChannelTestView)
async def test_channel(
    channel_id: UUID,
    request: Request,
    db: DB,
    body: ChannelProbe,
    _csrf: Mutation,
) -> ChannelTestView:
    from app.modules.llm.channel_testing import run

    return await run(channel_id, request, db, body)


@router.post(
    "/channels/{channel_id}/diagnostics",
    response_model=ChannelTestView,
    responses={
        200: {
            "description": "Single diagnostic result, or named SSE events for streaming Chat.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def channel_diagnostic(
    channel_id: UUID, request: Request, db: DB, body: DiagnosticRequest, _csrf: Mutation
) -> ChannelTestView | StreamingResponse:
    from app.modules.llm.diagnostics import run_diagnostic

    return await run_diagnostic(channel_id, request, db, body)


@router.get("/diagnostics/{request_id}", response_model=DiagnosticDetail)
async def diagnostic_record(request_id: UUID, request: Request, db: DB) -> DiagnosticDetail:
    from app.modules.llm.diagnostics import diagnostic_detail

    return await diagnostic_detail(request_id, request, db)


@router.get("/channels/{channel_id}/tests", response_model=list[ChannelTestRecord])
async def test_history(
    channel_id: UUID,
    request: Request,
    db: DB,
    page: int = Query(default=1, ge=1, le=10000),
    operation: Literal["chat", "embedding", "rerank", "image_generation", "speech"] | None = None,
    status: Literal["success", "failure", "unconfirmed"] | None = None,
    channel_version: int | None = Query(default=None, ge=1),
) -> list[ChannelTestRecord]:
    from app.modules.llm.channel_testing import history

    return await history(
        channel_id,
        request,
        db,
        page,
        operation=operation,
        status=status,
        channel_version=channel_version,
    )


@router.put(
    "/channels/{channel_id}",
    response_model=ChannelDetail,
    summary="修改渠道配置",
    responses={409: {"model": ChannelRemovalConflictResponse}},
)
async def update(
    channel_id: UUID, request: Request, db: DB, body: ChannelUpdate, _csrf: Mutation
) -> ChannelDetail:
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    editable(row)
    await configure(request, db, actor, body, row)
    row.version += 1
    record(db, actor, "llm.channel.update", row.id, row.name)
    result = view(row)
    await db.commit()
    return result


@router.put(
    "/channels/{channel_id}/status",
    response_model=ChannelDetail,
    summary="管理员按版本启停渠道",
)
async def status(
    channel_id: UUID, request: Request, db: DB, body: ChannelStatusInput, _csrf: Mutation
) -> ChannelDetail:
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    editable(row)
    row.manual_enabled = body.manual_enabled
    row.version += 1
    record(db, actor, "llm.channel.status", row.id, row.name)
    result = view(row)
    await db.commit()
    return result


@router.post(
    "/channels/status-batch",
    response_model=ChannelStatusBatchResult,
    summary="逐项版本化启停最多五十条渠道",
)
async def status_batch(
    request: Request, db: DB, body: ChannelStatusBatch, _csrf: Mutation
) -> ChannelStatusBatchResult:
    results: list[ChannelStatusResult] = []
    for item in body.items:
        # Re-authenticate and acquire the tenant lock for every independent item.
        actor = await administrator(request, db, write=True)
        row = await db.scalar(
            select(ModelChannel)
            .where(ModelChannel.tenant_id == actor.tenant.id, ModelChannel.id == item.id)
            .execution_options(populate_existing=True)
        )
        if row is None:
            results.append(ChannelStatusResult(id=item.id, status="not_found"))
        elif row.version != item.version:
            results.append(ChannelStatusResult(id=item.id, status="conflict", version=row.version))
        elif row.archived:
            results.append(ChannelStatusResult(id=item.id, status="archived", version=row.version))
        else:
            row.manual_enabled = item.manual_enabled
            row.version += 1
            record(db, actor, "llm.channel.status", row.id, row.name)
            results.append(ChannelStatusResult(id=item.id, status="updated", version=row.version))
        await db.commit()
    return ChannelStatusBatchResult(items=results)


@router.put(
    "/channels/{channel_id}/archive", response_model=ChannelDetail, summary="归档或恢复渠道"
)
async def archive(
    channel_id: UUID, request: Request, db: DB, body: ArchiveInput, _csrf: Mutation
) -> ChannelDetail:
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    row.archived = body.archived
    row.version += 1
    row.snapshot_id = None
    record(
        db,
        actor,
        "llm.channel.archive" if body.archived else "llm.channel.restore",
        row.id,
        row.name,
    )
    result = view(row)
    await db.commit()
    return result


async def inspect(
    channel_id: UUID, request: Request, db: DB, body: Version, *, discover: bool
) -> DiscoveryView:
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    editable(row)
    base, timeout, provider_id, connection = (
        row.base_url,
        row.timeout_seconds,
        row.provider,
        row.connection,
    )
    key = str(provider(request).unseal(row.sealed_key)["key"]) if row.sealed_key else None
    # Never hold organization locks across external IO. Revalidate after the request.
    await db.commit()
    listing = None
    try:
        connection_kwargs = (
            {"connection": connection}
            if connection and connection.get("address_mode") != "legacy_api_base"
            else {}
        )
        listing = await PROVIDERS[provider_id].list_models(
            base, key, timeout, provider(request).settings, **connection_kwargs
        )
        message = f"模型目录读取成功，返回 {len(listing.models)} 个模型"
        if listing.partial:
            message += "（上游还有更多结果，可手动登记其余模型）"
    except HTTPException as exc:
        message = str(exc.detail)
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    editable(row)
    check = CheckRecord(
        at=now(), ok=listing is not None, message=message, kind="discovery" if discover else "check"
    )
    row.checks = [check.model_dump(mode="json"), *row.checks[:19]]
    snapshot_id = None
    if discover and listing is not None:
        cache_directory(row, listing)
        snapshot_id = row.snapshot_id
    row.version += 1
    record(
        db,
        actor,
        "llm.channel.discover" if discover else "llm.channel.check",
        row.id,
        row.name,
        result="success" if listing else "failure",
    )
    result = DiscoveryView(
        channel=view(row),
        ok=listing is not None,
        message=message,
        snapshot_id=snapshot_id,
        candidates=listing.models if listing and discover else [],
        partial=listing.partial if listing else False,
    )
    await db.commit()
    return result


@router.post(
    "/channels/{channel_id}/check",
    response_model=DiscoveryView,
    summary="读取模型目录检查连接，不调用推理接口",
)
async def check(
    channel_id: UUID, request: Request, db: DB, body: Version, _csrf: Mutation
) -> DiscoveryView:
    return await inspect(channel_id, request, db, body, discover=False)


@router.post(
    "/channels/{channel_id}/discover",
    response_model=DiscoveryView,
    summary="发现模型候选；不自动登记或发布",
)
async def discover(
    channel_id: UUID, request: Request, db: DB, body: Version, _csrf: Mutation
) -> DiscoveryView:
    return await inspect(channel_id, request, db, body, discover=True)


@router.post(
    "/channels/{channel_id}/models",
    response_model=ChannelDetail,
    summary="登记选定或手工填写的模型 ID",
)
async def register_models(
    channel_id: UUID, request: Request, db: DB, body: ModelsInput, _csrf: Mutation
) -> ChannelDetail:
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    editable(row)
    if body.snapshot_id and (
        body.snapshot_id != row.snapshot_id
        or not row.snapshot_at
        or not {m.id for m in body.models}.issubset(row.snapshot)
    ):
        raise HTTPException(409, "模型列表已更新或连接已变更，请刷新渠道后重新选择")
    existing = {m["id"]: m for m in row.models}
    for model in body.models:
        if model.id not in existing:
            existing[model.id] = RegisteredModel(
                id=model.id,
                source="discovery" if body.snapshot_id else "manual",
                registered_at=now(),
            ).model_dump(mode="json")
    if len(existing) > 1000:
        raise HTTPException(422, "每个渠道最多登记 1000 个模型")
    validate_registered_targets(row.provider, row.base_url, row.connection, list(existing.values()))
    row.models = list(existing.values())
    row.version += 1
    record(
        db, actor, "llm.channel.models", row.id, row.name, details={"count": str(len(body.models))}
    )
    result = view(row)
    await db.commit()
    return result


@router.delete(
    "/channels/{channel_id}/models",
    response_model=ChannelDetail,
    summary="移除已登记模型",
    responses={409: {"model": ChannelRemovalConflictResponse}},
)
async def remove_models(
    channel_id: UUID, request: Request, db: DB, body: ModelsInput, _csrf: Mutation
) -> ChannelDetail:
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    editable(row)
    ids = {m.id for m in body.models}
    await assert_inventory_removable(db, row, ids & {m["id"] for m in row.models})
    row.models = [m for m in row.models if m["id"] not in ids]
    row.version += 1
    record(
        db, actor, "llm.channel.models.remove", row.id, row.name, details={"count": str(len(ids))}
    )
    result = view(row)
    await db.commit()
    return result
