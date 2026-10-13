from decimal import Decimal, localcontext
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, now
from app.modules.llm import routing
from app.modules.llm.binding_identity import (
    project_binding_ids,
    projected_binding_id,
    reconcile_binding_ids,
)
from app.modules.llm.catalog_schemas import (
    RATE_FIELDS,
    BindingState,
    CatalogInput,
    CatalogPage,
    CatalogUpdate,
    CatalogView,
    EstimateItem,
    OperationKind,
    OperationParameters,
    PriceEstimateInput,
    PriceEstimateView,
)
from app.modules.llm.model_candidates import MatchMode, ModelCandidatePage, candidates
from app.modules.llm.model_endpoints import ModelEndpoints, project_endpoints, summarize_endpoints
from app.modules.llm.models import CatalogModel, ModelChannel, PointConversion, RouteHealth
from app.modules.llm.points import current_conversion, point_price
from app.modules.llm.reference_price_preview import (
    ReferencePricePreview,
    ReferencePricePreviewInput,
)
from app.modules.llm.reference_price_preview import (
    preview as reference_price_preview,
)
from app.modules.llm.router import administrator
from app.modules.llm.schemas import ArchiveInput
from app.modules.mcp.schemas import normalize_icon
from app.modules.members.service import Access, record

router = APIRouter(prefix="/api/v1/llm", tags=["llm-models"])


@router.get("/model-candidates")
async def model_candidates(
    request: Request,
    db: DB,
    kind: OperationKind,
    q: str = Query(default="", max_length=200),
    match: MatchMode = "exact",
    page: int = Query(default=1, ge=1),
) -> ModelCandidatePage:
    actor = await administrator(request, db)
    channels = (
        await db.scalars(
            select(ModelChannel).where(
                ModelChannel.tenant_id == actor.tenant.id, ModelChannel.archived.is_(False)
            )
        )
    ).all()
    return candidates(list(channels), q.strip(), match, kind, page)


@router.post("/reference-price-preview")
async def preview_reference_price(
    request: Request, db: DB, body: ReferencePricePreviewInput, _mutation: Mutation
) -> ReferencePricePreview:
    await administrator(request, db)
    try:
        return reference_price_preview(body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


async def get_model(
    db: DB, actor: Access, model_id: UUID, version: int | None = None
) -> CatalogModel:
    row = await db.scalar(
        select(CatalogModel)
        .where(CatalogModel.tenant_id == actor.tenant.id, CatalogModel.id == model_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404, "模型不存在")
    if version is not None and row.version != version:
        raise HTTPException(409, "模型已被修改，请关闭并重新打开配置")
    return row


async def channel_map(
    db: DB, tenant_id: UUID, configs: list[CatalogInput]
) -> dict[UUID, ModelChannel]:
    ids = {
        b.channel_id
        for config in configs
        for operation in config.operation_configs()
        for b in operation.bindings
    }
    if not ids:
        return {}
    rows = await db.scalars(
        select(ModelChannel).where(ModelChannel.tenant_id == tenant_id, ModelChannel.id.in_(ids))
    )
    return {row.id: row for row in rows}


def view(
    row: CatalogModel, channels: dict[UUID, ModelChannel], conversion: PointConversion | None = None
) -> CatalogView:
    config = CatalogInput.model_validate(row.configuration)
    config = project_binding_ids(row.id, config)
    states = []
    for operation, binding in [(o.kind, b) for o in config.operation_configs() for b in o.bindings]:
        upstream = channels.get(binding.channel_id)
        state: Literal["registered", "archived", "missing"] = "missing"
        if upstream is not None:
            if upstream.archived:
                state = "archived"
            elif any(m["id"] == binding.upstream_id for m in upstream.models):
                state = "registered"
        states.append(
            BindingState(
                operation=operation,
                binding_id=projected_binding_id(row.id, operation, binding),
                channel_id=binding.channel_id,
                upstream_id=binding.upstream_id,
                channel_name=upstream.name if upstream else "渠道不可用",
                state=state,
            )
        )
    return CatalogView(
        **config.model_dump(),
        id=row.id,
        version=row.version,
        archived=row.archived,
        binding_states=states,
        created_at=row.created_at,
        updated_at=row.updated_at,
        point_price=point_price(config.budget_price, conversion),
        operation_point_prices={
            o.kind: point_price(o.budget_price, conversion) for o in config.operation_configs()
        },
    )


async def projected_view(
    db: DB,
    row: CatalogModel,
    channels: dict[UUID, ModelChannel],
    conversion: PointConversion | None,
    health_snapshot: dict[str, RouteHealth] | None = None,
) -> CatalogView:
    result = view(row, channels, conversion)
    with db.no_autoflush:
        projection = await project_endpoints(
            db, row.tenant_id, row, result, channels, health_snapshot=health_snapshot
        )
    result.endpoint_summary = summarize_endpoints(projection)
    return result


async def configure(
    db: DB, actor: Access, row: CatalogModel, body: CatalogInput
) -> dict[UUID, ModelChannel]:
    duplicate = await db.scalar(
        select(CatalogModel.id).where(
            CatalogModel.tenant_id == actor.tenant.id,
            CatalogModel.slug == body.slug,
            CatalogModel.id != row.id,
        )
    )
    if duplicate:
        raise HTTPException(409, "技术名称已存在（包括已归档模型）")
    if row.configuration and body.operations is None:
        legacy_previous = CatalogInput.model_validate(row.configuration)
        if len(legacy_previous.operation_configs()) != 1:
            raise HTTPException(409, "请刷新页面后编辑多操作模型")
    if body.operations is not None:
        kinds = [operation.kind for operation in body.operations]
        if len(kinds) != len(set(kinds)):
            raise HTTPException(422, "同一操作只能配置一次")
    submitted_channels = await channel_map(db, actor.tenant.id, [body])
    if any(
        binding.channel_id not in submitted_channels
        for operation in body.operation_configs()
        for binding in operation.bindings
    ):
        raise HTTPException(422, "关联渠道不存在或不属于当前组织")
    provided_fields = body.model_fields_set.copy()
    previous_config = CatalogInput.model_validate(row.configuration) if row.configuration else None
    if previous_config and body.operations is None and "kind" not in provided_fields:
        old_operations = previous_config.operation_configs()
        if old_operations:
            # CatalogUpdate skips cross-field projection; infer the existing
            # single operation before matching omitted binding identities.
            body = body.model_copy(update={"kind": old_operations[0].kind})
    body = reconcile_binding_ids(row.id, body, previous_config)
    row.name, row.slug = body.name, body.slug
    data = body.model_dump(mode="json", exclude={"version"})
    if previous_config and previous_config.operations is not None and body.operations is None:
        # A legacy single-operation client updates the one operation without
        # dropping the operations array or resetting fields it did not send.
        operation = previous_config.operations[0].model_dump(mode="json")
        for key in OperationParameters.model_fields:
            if key in provided_fields:
                operation[key] = data[key]
        operation["bindings"] = data["bindings"]
        if "access" in provided_fields:
            operation.update(
                enabled=body.access.enabled,
                channel_id=str(body.access.channel_id) if body.access.channel_id else None,
                upstream_id=body.access.upstream_id,
            )
        data["operations"] = [operation]
    # Omitted extension fields from older clients must not erase new configuration.
    for key in (
        "icon",
        "icon_key",
        "reference",
        "display_order",
        "quote_snapshots",
        "reasoning_options",
        "kind",
        "retrieval",
        "image",
        "speech",
        "transcription",
        "chat_policy",
        "access",
        "routing",
    ):
        if key not in provided_fields and key in (row.configuration or {}):
            data[key] = row.configuration[key]
    if "reasoning" not in body.capabilities.model_fields_set:
        data["capabilities"]["reasoning"] = (
            (row.configuration or {}).get("capabilities", {}).get("reasoning", "unknown")
        )
    if (
        data["capabilities"]["reasoning"] != "supported"
        and "reasoning_options" not in provided_fields
    ):
        data["reasoning_options"] = []
    if "icon" in provided_fields and body.icon != (row.configuration or {}).get("icon", ""):
        data["icon"] = normalize_icon(body.icon)
    # Revalidate the merged configuration before persisting it.
    try:
        validated = CatalogInput.model_validate(data)
    except ValidationError as exc:
        raise HTTPException(422, "模型用途、参数与价格配置不一致") from exc
    channels = await channel_map(db, actor.tenant.id, [validated])
    previous = (
        {
            (o.kind, str(b.channel_id), b.upstream_id)
            for o in previous_config.operation_configs()
            for b in o.bindings
        }
        if previous_config
        else set()
    )
    previously_enabled = (
        {
            (o.kind, str(b.channel_id), b.upstream_id)
            for o in previous_config.operation_configs()
            for b in o.bindings
            if b.enabled
        }
        if previous_config
        else set()
    )
    for op_config in validated.operation_configs():
        for binding in op_config.bindings:
            upstream = channels.get(binding.channel_id)
            if upstream is None:
                raise HTTPException(422, "关联渠道不存在或不属于当前组织")
            target = (op_config.kind, str(binding.channel_id), binding.upstream_id)
            if (
                target not in previous or binding.enabled and target not in previously_enabled
            ) and (
                upstream.archived
                or not any(m["id"] == binding.upstream_id for m in upstream.models)
            ):
                raise HTTPException(422, "请从未归档渠道的已登记模型中选择关联")
    from app.modules.llm.runtime import validate_configuration

    if previous_config:
        # Route fingerprints predate stable binding IDs and must stay compatible.
        # Forget only detached/replaced identities, before checking new route readiness.
        # Credential health is shared by the channel and is deliberately retained.
        def identities(value: CatalogInput) -> dict[tuple[object, ...], str]:
            return {
                (
                    op.kind,
                    projected_binding_id(row.id, op.kind, binding),
                    binding.channel_id,
                    binding.upstream_id,
                ): routing.health_key(actor.tenant.id, row.id, op.kind, binding)
                for op in value.operation_configs()
                for binding in op.bindings
            }

        old_identities, new_identities = identities(previous_config), identities(validated)
        changed = old_identities.keys() ^ new_identities.keys()
        invalidated = {
            old_identities.get(identity) or new_identities[identity] for identity in changed
        }
        if invalidated:
            await db.execute(
                delete(RouteHealth).where(
                    RouteHealth.tenant_id == actor.tenant.id, RouteHealth.id.in_(invalidated)
                )
            )
    await validate_configuration(db, actor, row, validated, channels)
    row.configuration = validated.model_dump(mode="json")
    row.updated_at = now()
    return channels


@router.get("/models", response_model=CatalogPage, summary="管理员模型配置目录")
async def listing(
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=100),
    state: Literal["current", "archived", "all"] = "current",
    page: int = Query(default=1, ge=1),
    kind: Literal["chat", "embedding", "rerank", "image_generation"] | None = None,
) -> CatalogPage:
    actor = await administrator(request, db)
    filters = [CatalogModel.tenant_id == actor.tenant.id]
    if kind:
        filters.append(
            or_(
                CatalogModel.configuration["operations"].contains([{"kind": kind}]),
                (func.coalesce(CatalogModel.configuration["operations"].astext, "null") == "null")
                & (func.coalesce(CatalogModel.configuration["kind"].astext, "chat") == kind),
            )
        )
    if state != "all":
        filters.append(CatalogModel.archived == (state == "archived"))
    if q.strip():
        filters.append(
            or_(
                CatalogModel.name.icontains(q.strip(), autoescape=True),
                CatalogModel.slug.icontains(q.strip(), autoescape=True),
            )
        )
    total = await db.scalar(select(func.count()).select_from(CatalogModel).where(*filters))
    rows = list(
        await db.scalars(
            select(CatalogModel)
            .where(*filters)
            .order_by(CatalogModel.created_at.desc(), CatalogModel.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
    )
    channels = await channel_map(
        db, actor.tenant.id, [CatalogInput.model_validate(r.configuration) for r in rows]
    )
    conversion = await current_conversion(db, actor.tenant.id)
    # One scoped read per page, not two health reads for every possible binding.
    health_ids = {routing.credential_key(channel) for channel in channels.values()}
    for row in rows:
        for operation in CatalogInput.model_validate(row.configuration).operation_configs():
            health_ids.update(
                routing.health_key(actor.tenant.id, row.id, operation.kind, binding)
                for binding in operation.bindings
            )
    with db.no_autoflush:
        health_rows = await db.scalars(
            select(RouteHealth).where(
                RouteHealth.tenant_id == actor.tenant.id, RouteHealth.id.in_(health_ids)
            )
        )
        health_snapshot = {item.id: item for item in health_rows}
    return CatalogPage(
        items=[await projected_view(db, r, channels, conversion, health_snapshot) for r in rows],
        total=total or 0,
    )


@router.post("/models", response_model=CatalogView, summary="原子保存模型、价格及调用设置")
async def create(request: Request, db: DB, body: CatalogInput, _csrf: Mutation) -> CatalogView:
    actor = await administrator(request, db, write=True)
    row = CatalogModel(id=uuid4(), tenant_id=actor.tenant.id)
    channels = await configure(db, actor, row, body)
    db.add(row)
    await db.flush()
    record(db, actor, "llm.model.create", row.id, row.name)
    result = view(row, channels, await current_conversion(db, actor.tenant.id))
    await db.commit()
    return result


@router.get("/models/{model_id}", response_model=CatalogView, summary="管理员模型、映射与价格配置")
async def detail(model_id: UUID, request: Request, db: DB) -> CatalogView:
    actor = await administrator(request, db)
    row = await get_model(db, actor, model_id)
    channels = await channel_map(
        db, actor.tenant.id, [CatalogInput.model_validate(row.configuration)]
    )
    return await projected_view(db, row, channels, await current_conversion(db, actor.tenant.id))


@router.get(
    "/models/{model_id}/endpoints",
    response_model=ModelEndpoints,
    summary="管理员查看当前平台模型调用端点",
)
async def endpoints(model_id: UUID, request: Request, db: DB) -> ModelEndpoints:
    actor = await administrator(request, db)
    row = await get_model(db, actor, model_id)
    config = CatalogInput.model_validate(row.configuration)
    channels = await channel_map(db, actor.tenant.id, [config])
    return await project_endpoints(db, actor.tenant.id, row, config, channels)


@router.put("/models/{model_id}", response_model=CatalogView, summary="版本化修改模型与价格配置")
async def update(
    model_id: UUID, request: Request, db: DB, body: CatalogUpdate, _csrf: Mutation
) -> CatalogView:
    actor = await administrator(request, db, write=True)
    row = await get_model(db, actor, model_id, body.version)
    if row.archived:
        raise HTTPException(409, "请先恢复已归档模型")
    channels = await configure(db, actor, row, body)
    row.version += 1
    record(db, actor, "llm.model.update", row.id, row.name)
    result = view(row, channels, await current_conversion(db, actor.tenant.id))
    await db.commit()
    return result


@router.put("/models/{model_id}/archive", response_model=CatalogView, summary="归档或恢复模型配置")
async def archive(
    model_id: UUID, request: Request, db: DB, body: ArchiveInput, _csrf: Mutation
) -> CatalogView:
    actor = await administrator(request, db, write=True)
    row = await get_model(db, actor, model_id, body.version)
    row.archived, row.updated_at = body.archived, now()
    if body.archived:
        configuration = CatalogInput.model_validate(row.configuration)
        configuration.access.enabled = False
        row.configuration = configuration.model_dump(mode="json")
    row.version += 1
    channels = await channel_map(
        db, actor.tenant.id, [CatalogInput.model_validate(row.configuration)]
    )
    record(
        db, actor, "llm.model.archive" if body.archived else "llm.model.restore", row.id, row.name
    )
    result = view(row, channels, await current_conversion(db, actor.tenant.id))
    await db.commit()
    return result


@router.post(
    "/prices/estimate", response_model=PriceEstimateView, summary="按互斥用量试算草稿价格，不扣费"
)
async def estimate(
    request: Request, db: DB, body: PriceEstimateInput, _csrf: Mutation
) -> PriceEstimateView:
    actor = await administrator(request, db)
    if body.price.metric != "tokens" and any(getattr(body.usage, k) for k in RATE_FIELDS[1:]):
        raise HTTPException(422, "非 Token 计价只接受输入计量")
    items = []
    with localcontext() as context:
        context.prec = 60
        total = Decimal(0)
        for key in RATE_FIELDS:
            tokens, rate = getattr(body.usage, key), getattr(body.price, key)
            if tokens and rate is None:
                raise HTTPException(422, f"{key} 有用量但尚未配置单价")
            amount = Decimal(tokens) * rate / body.price.unit if rate is not None else Decimal(0)
            total += amount
            items.append(
                EstimateItem(
                    item=key,
                    tokens=tokens,
                    rate=format(rate, "f") if rate is not None else None,
                    amount=format(amount, "f"),
                )
            )
    points = None
    if body.include_points:
        points = point_price(body.price, await current_conversion(db, actor.tenant.id), total)
    return PriceEstimateView(
        currency=body.price.currency, total=format(total, "f"), items=items, points=points
    )
