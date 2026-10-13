"""One authorized, live-route model projection for public and account catalogs."""

from __future__ import annotations

from typing import Literal, cast
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import Integer, func, select
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.access_keys import service as keys
from app.modules.llm import runtime
from app.modules.llm.catalog_schemas import (
    CatalogInput,
    OperationKind,
    effective_reasoning_format,
)
from app.modules.llm.inference_schemas import (
    PublicChatRoute,
    PublicModel,
    PublicModels,
    PublicOperation,
)
from app.modules.llm.model_endpoints import PATHS, _example
from app.modules.llm.models import CatalogModel
from app.modules.llm.points import current_conversion, point_price
from app.modules.members.service import BusinessActor


class MemberEndpointView(BaseModel):
    method: Literal["POST"] = "POST"
    path: str
    inbound_protocol: Literal["openai_compatible"] = "openai_compatible"
    stream: bool
    tools: bool
    example: dict[str, object]


class MemberOperationView(PublicOperation):
    endpoint: MemberEndpointView
    point_price_status: Literal["ready", "no_price", "unconfigured", "currency_mismatch"]


class MemberModelView(BaseModel):
    id: UUID
    slug: str
    name: str
    display_order: int = 0
    resource: str
    operations: list[MemberOperationView]


class MemberModelPage(BaseModel):
    items: list[MemberModelView]
    total: int
    page: int
    page_size: int = 20
    has_more: bool


async def available_models(
    db: AsyncSession, actor: BusinessActor
) -> list[tuple[UUID, PublicModel, dict[OperationKind, str]]]:
    """Filter current member permission and route readiness before any pagination.

    This is deliberately shared by the Bearer catalog and account session catalog.
    It reads route health but never claims a route, sends upstream I/O or activates quota.
    """
    rows = await db.scalars(
        select(CatalogModel)
        .where(CatalogModel.tenant_id == actor.tenant.id, CatalogModel.archived.is_(False))
        .order_by(
            func.coalesce(
                sql_cast(CatalogModel.configuration["display_order"].astext, Integer), 0
            ).desc(),
            CatalogModel.slug,
            CatalogModel.id,
        )
    )
    available: list[tuple[UUID, PublicModel, dict[OperationKind, str]]] = []
    conversion = await current_conversion(db, actor.tenant.id)
    for row in rows:
        config = CatalogInput.model_validate(row.configuration)
        if not runtime.visible(config, actor) or not keys.permits(actor, "llm", row.id, "read"):
            continue
        operations: list[PublicOperation] = []
        price_statuses: dict[OperationKind, str] = {}
        for operation in config.execution_configs():
            if not runtime.visible(operation, actor):
                continue
            try:
                await runtime.channel_for(db, actor, operation, row.id)
            except HTTPException:
                continue
            from app.modules.llm import routing
            from app.modules.llm.chat_policy import resolve, route_limits, supports
            from app.modules.llm.chat_schemas import ChatInput, ChatMessage
            from app.modules.llm.providers import PROVIDERS

            profiles = []
            default_ready = False
            try:
                default_request = (
                    resolve(
                        ChatInput(
                            model=operation.slug, messages=[ChatMessage(role="user", content="hi")]
                        ),
                        operation,
                        row.version,
                    )
                    if operation.kind == "chat"
                    else None
                )
            except HTTPException:
                default_request = None
            if operation.kind == "chat":
                channels = await routing.channels_for(db, actor.tenant.id, operation)
                for binding in operation.bindings:
                    if operation.routing.mode == "fixed" and (
                        binding.channel_id,
                        binding.upstream_id,
                    ) != (operation.access.channel_id, operation.access.upstream_id):
                        continue
                    channel = channels.get(binding.channel_id)
                    state, _ = await routing.state(
                        db,
                        actor.tenant.id,
                        row.id,
                        operation,
                        binding,
                        channel,
                        require_test=operation.routing.mode == "auto",
                    )
                    if state == "ready" and channel:
                        profile = PublicChatRoute(
                            **route_limits(operation, binding, channel).model_dump(),
                            reasoning_format=effective_reasoning_format(
                                binding.chat_options.reasoning_format,
                                operation.reasoning_options,
                            )
                            if PROVIDERS[channel.provider].sdk_provider == "openai"
                            else "thinking_budget",
                        )
                        if default_request is not None and supports(
                            default_request, operation, binding, channel
                        ):
                            default_ready = True
                        if profile not in profiles:
                            profiles.append(profile)
            point_price_view = point_price(operation.budget_price, conversion)
            price_statuses[operation.kind] = point_price_view.status
            operations.append(
                PublicOperation(
                    parameter_routes=profiles,
                    default_parameters_ready=default_ready if operation.kind == "chat" else None,
                    pricing_status=point_price_view.status,
                    input_modalities=["text", "image"]
                    if operation.kind == "chat" and operation.capabilities.vision == "supported"
                    else ["audio"]
                    if operation.kind == "transcription"
                    else ["text"],
                    output_modalities=["audio"]
                    if operation.kind == "speech"
                    else ["image"]
                    if operation.kind == "image_generation"
                    else ["text"]
                    if operation.kind in {"chat", "transcription"}
                    else ["vector"]
                    if operation.kind == "embedding"
                    else ["scores"],
                    kind=operation.kind,
                    image=operation.image if operation.kind == "image_generation" else None,
                    speech=operation.speech if operation.kind == "speech" else None,
                    transcription=operation.transcription
                    if operation.kind == "transcription"
                    else None,
                    chat_policy=operation.chat_policy if operation.kind == "chat" else None,
                    limits=operation.retrieval,
                    capabilities=operation.capabilities,
                    context_window=operation.context_window,
                    max_output=operation.max_output,
                    reasoning_options=operation.reasoning_options,
                    point_rates=point_price_view.rates,
                    metric=operation.budget_price.metric if operation.budget_price else "tokens",
                    unit=point_price_view.unit,
                )
            )
        if operations:
            available.append(
                (
                    row.id,
                    PublicModel(
                        configuration_version=row.version,
                        description=config.description,
                        vendor=config.vendor,
                        icon=config.icon,
                        icon_key=config.icon_key,
                        resource="llm:" + str(row.id),
                        created=int(row.created_at.timestamp()),
                        id=config.slug,
                        name=config.name,
                        display_order=config.display_order,
                        operations=operations,
                        **operations[0].model_dump(),
                    ),
                    price_statuses,
                )
            )
    return available


async def public_page(db: AsyncSession, actor: BusinessActor, page: int) -> PublicModels:
    available = await available_models(db, actor)
    start = (page - 1) * 20
    return PublicModels(
        data=[model for _, model, _ in available[start : start + 20]],
        has_more=start + 20 < len(available),
        page=page,
    )


async def member_page(
    db: AsyncSession,
    actor: BusinessActor,
    *,
    q: str = "",
    operation: OperationKind | None = None,
    page: int = 1,
) -> MemberModelPage:
    available = await available_models(db, actor)
    term = q.strip().casefold()
    filtered = [
        (model_id, model, statuses)
        for model_id, model, statuses in available
        if (not term or term in model.id.casefold() or term in model.name.casefold())
        and (operation is None or any(item.kind == operation for item in model.operations))
    ]
    start = (page - 1) * 20
    items = [
        MemberModelView(
            id=model_id,
            slug=model.id,
            name=model.name,
            display_order=model.display_order,
            resource=model.resource,
            operations=[
                MemberOperationView(
                    **item.model_dump(),
                    point_price_status=cast(
                        Literal["ready", "no_price", "unconfigured", "currency_mismatch"],
                        statuses[item.kind],
                    ),
                    endpoint=MemberEndpointView(
                        path=PATHS[item.kind],
                        stream=item.kind == "chat" and item.capabilities.streaming != "unsupported",
                        tools=item.kind == "chat" and item.capabilities.tools != "unsupported",
                        example=_example(item.kind, model.id),
                    ),
                )
                for item in model.operations
                if operation is None or item.kind == operation
            ],
        )
        for model_id, model, statuses in filtered[start : start + 20]
    ]
    return MemberModelPage(
        items=items,
        total=len(filtered),
        page=page,
        has_more=start + 20 < len(filtered),
    )
