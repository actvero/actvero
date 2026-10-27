"""Device-bound model calls with bounded failover and monetary settlement."""

import secrets
import time
from collections.abc import AsyncGenerator
from contextlib import aclosing
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.access_keys import service as keys
from app.modules.auth.service import digest, limit, now, provider
from app.modules.desktop import service as desktop
from app.modules.desktop.errors import fail
from app.modules.desktop.models import DeviceSession
from app.modules.desktop.resources import actor_for_membership
from app.modules.desktop_mcp.models import ResourceToken
from app.modules.desktop_mcp.schemas import ResourceTokenView
from app.modules.desktop_mcp.service import NativeActor, business_actor
from app.modules.llm import routing, settlement
from app.modules.llm.audio_schemas import SpeechInput, TranscriptionInput
from app.modules.llm.catalog_schemas import CatalogInput, OperationKind, TokenPrice
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.image_schemas import ImageInput
from app.modules.llm.inference_schemas import (
    EmbeddingInput,
    EmbeddingOutput,
    RerankInput,
    RerankOutput,
)
from app.modules.llm.models import CatalogModel, ModelCall, ModelChannel
from app.modules.llm.providers import (
    PROVIDERS,
    chat,
    retrieval,
    sdk_images,
    sdk_speech,
    sdk_transcription,
)
from app.modules.llm.request_identity import request_fingerprint
from app.modules.llm.router import administrator
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor
from app.modules.tenants.models import Tenant

BASE = "/api/llm/v1"


def visible(config: CatalogInput, actor: BusinessActor) -> bool:
    if config.operations is not None:
        return any(visible(operation, actor) for operation in config.execution_configs())
    policy = config.access
    return policy.enabled and (
        policy.audience == "organization"
        or policy.audience == "administrators"
        and actor.member.role == "administrator"
        or policy.audience == "selected"
        and actor.member.id in policy.member_ids
    )


def route(config: CatalogInput, channels: dict[UUID, ModelChannel]) -> ModelChannel:
    policy = config.access
    row = channels.get(policy.channel_id) if policy.channel_id else None
    if row is None or row.archived or not any(m["id"] == policy.upstream_id for m in row.models):
        fail(409, "route_unavailable", "调用渠道未选择、已归档或上游模型已移除")
    if not any(
        b.enabled and b.channel_id == row.id and b.upstream_id == policy.upstream_id
        for b in config.bindings
    ):
        fail(409, "route_unavailable", "调用渠道不在模型关联清单中")
    api = {
        "chat": "chat_completions",
        "embedding": "embeddings",
        "rerank": "rerank",
        "image_generation": "images",
        "speech": "speech",
        "transcription": "transcriptions",
    }[config.kind]
    if api not in row.declared_apis:
        fail(409, "protocol_not_configured", "请先在渠道高级设置中声明对应接口")
    if config.kind not in PROVIDERS[row.provider].info.member_operations:
        fail(409, "operation_unavailable", "该供应商尚未接入此操作")
    if row.auth_mode == "api_key" and not row.sealed_key:
        fail(409, "credentials_required", "渠道尚未配置凭据")
    return row


async def validate_configuration(
    db: AsyncSession,
    actor: BusinessActor,
    row: CatalogModel,
    config: CatalogInput,
    channels: dict[UUID, ModelChannel],
) -> None:
    if config.access.audience == "selected":
        ids = set(
            await db.scalars(
                select(Membership.id).where(
                    Membership.id.in_(config.access.member_ids),
                    Membership.tenant_id == actor.tenant.id,
                    Membership.status == "active",
                )
            )
        )
        if ids != set(config.access.member_ids):
            fail(422, "invalid_members", "请选择本组织的有效成员")
    for operation in config.execution_configs():
        if operation.access.enabled:
            if operation.routing.mode == "fixed":
                route(operation, channels)
            else:
                routing.configured_candidates(operation, channels)
    previous = CatalogInput.model_validate(row.configuration) if row.configuration else None
    old_embedding = previous.for_operation("embedding") if previous else None
    embedding = config.for_operation("embedding")
    if old_embedding and (
        embedding is None
        or old_embedding.slug != embedding.slug
        or old_embedding.retrieval.dimensions != embedding.retrieval.dimensions
        or old_embedding.retrieval.embedding_space != embedding.retrieval.embedding_space
        or old_embedding.retrieval.dimension_options != embedding.retrieval.dimension_options
    ):
        used = await db.scalar(
            select(ModelCall.id)
            .where(
                ModelCall.model_id == row.id,
                ModelCall.kind == "embedding",
                ModelCall.source.in_(["desktop", "access_key"]),
            )
            .limit(1)
        )
        if used:
            fail(
                409,
                "embedding_space_in_use",
                "已有客户端调用，请为新的向量空间或维度创建新模型标识",
            )


async def authorize(
    request: Request,
    db: AsyncSession,
    resource: str | None = None,
    *,
    in_flight: bool = False,
) -> BusinessActor:
    if keys.supplied(request):
        resource_id = (
            UUID(resource.removeprefix("llm:")) if resource and resource != "llm:catalog" else None
        )
        return await keys.authorize(
            request, db, "llm", resource_id, "read" if resource == "llm:catalog" else "invoke"
        )
    desktop.native_request(request)
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer avl_") or len(header) > 210:
        fail(401, "invalid_resource_token", "请使用 LLM 资源访问令牌")
    token_hash = digest(header[7:])
    token = await db.get(ResourceToken, token_hash, populate_existing=True)
    admitted = in_flight and getattr(request.state, "llm_admitted_token", None) == token_hash
    # Expiry limits admission, not the lifetime of an already-authorized stream.
    # Keep rechecking token existence, device, membership and model permissions.
    if not token or (token.expires_at <= now() and not admitted):
        fail(401, "resource_token_expired", "LLM 资源令牌已失效，请重新申请")
    expected = "llm:catalog" if token.resource == "llm:catalog" else "llm:invoke"
    if (
        not token.resource.startswith("llm:")
        or token.scope != expected
        or (resource is not None and token.resource != resource)
        or (resource is None and token.resource == "llm:catalog")
    ):
        fail(403, "resource_scope_mismatch", "此令牌不适用于当前资源")
    device = await db.get(DeviceSession, token.device_id, populate_existing=True)
    if not device:
        fail(401, "device_revoked", "设备登录已失效")
    actor = await actor_for_membership(
        db, await desktop.check_device(request, db, device), token.member_id
    )
    request.state.llm_resource = token.resource
    if not in_flight:
        request.state.llm_admitted_token = token_hash
    return actor


async def resolve_model(request: Request, db: AsyncSession, slug: str) -> UUID:
    actor = await authorize(request, db)
    if isinstance(actor, keys.KeyActor):
        row = await db.scalar(
            select(CatalogModel).where(
                CatalogModel.tenant_id == actor.tenant.id,
                CatalogModel.slug == slug,
                CatalogModel.archived.is_(False),
            )
        )
        if row is None:
            fail(404, "model_unavailable", "模型不存在或不可用")
        return row.id
    return UUID(request.state.llm_resource.removeprefix("llm:"))


async def model_for_actor(db: AsyncSession, actor: BusinessActor, model_id: UUID) -> CatalogModel:
    row = await db.get(CatalogModel, model_id, populate_existing=True)
    if row is None or row.tenant_id != actor.tenant.id or row.archived:
        fail(404, "model_unavailable", "模型不存在或不可用")
    return row


async def channel_for(
    db: AsyncSession, actor: BusinessActor, config: CatalogInput, model_id: UUID
) -> ModelChannel:
    channels = await routing.channels_for(db, actor.tenant.id, config)
    return routing.configured_candidates(config, channels)[0][1]


async def issue(request: Request, db: AsyncSession, resource: str) -> ResourceTokenView:
    actor = await business_actor(
        db,
        await desktop.desktop_actor(request, db),
        platform_edition=provider(request).settings.platform_edition,
    )
    await limit(db, "llm-resource:" + str(actor.device.id), 120, 60)
    actor = await business_actor(
        db,
        await desktop.desktop_actor(request, db),
        platform_edition=provider(request).settings.platform_edition,
    )
    if resource != "llm:catalog":
        try:
            model_id = UUID(resource.removeprefix("llm:"))
        except ValueError:
            fail(422, "invalid_resource", "模型资源标识无效")
        row = await model_for_actor(db, actor, model_id)
        config = CatalogInput.model_validate(row.configuration)
        if not visible(config, actor):
            fail(404, "model_unavailable", "模型未启用或未获授权")
        live = False
        for operation in config.execution_configs():
            if not visible(operation, actor):
                continue
            try:
                await channel_for(db, actor, operation, row.id)
                live = True
                break
            except HTTPException:
                continue
        if not live:
            fail(409, "route_unavailable", "没有已开放且可用的操作")
        resource = "llm:" + str(model_id)
    raw = "avl_" + secrets.token_urlsafe(32)
    expiry = min(now() + timedelta(seconds=600), actor.device.expires_at)
    scope = "llm:catalog" if resource == "llm:catalog" else "llm:invoke"
    db.add(
        ResourceToken(
            token_hash=digest(raw),
            device_id=actor.device.id,
            member_id=actor.member.id,
            resource=resource,
            scope=scope,
            expires_at=expiry,
        )
    )
    await db.commit()
    return ResourceTokenView(
        access_token=raw,
        resource=resource,
        scope=scope,
        expires_in=max(0, int((expiry - now()).total_seconds())),
        endpoint=provider(request).settings.app_url.rstrip("/") + BASE,
    )


def valuation(price: TokenPrice | None, usage: dict[str, Any]) -> dict[str, Any]:
    if price is None:
        return {"status": "price_missing"}
    amount = settlement.amount_for(price, usage)
    if amount is None:
        return {"status": "usage_unknown", "currency": price.currency}
    quantity = usage.get(
        {
            "tokens": "input_tokens",
            "characters": "input_characters",
            "search_units": "search_units",
            "images": "image_count",
            "seconds": "audio_duration_ms",
        }[price.metric]
    )
    if price.metric == "seconds" and quantity is not None:
        quantity = format(Decimal(str(quantity)) / Decimal(1000), "f")
    return {
        "status": "estimate",
        "currency": price.currency,
        "amount": format(amount, "f"),
        "metric": price.metric,
        "quantity": quantity,
    }


async def execute(
    request: Request,
    db: AsyncSession,
    model_id: UUID,
    body: EmbeddingInput | RerankInput | ChatInput | ImageInput | SpeechInput | TranscriptionInput,
    *,
    test: bool = False,
    specific: tuple[UUID, str] | None = None,
) -> AsyncGenerator[EmbeddingOutput | RerankOutput | dict[str, Any]]:
    actor = await administrator(request, db, write=True) if test else await authorize(request, db)
    if not test:
        await db.scalar(select(Tenant).where(Tenant.id == actor.tenant.id).with_for_update())
        actor = await authorize(request, db, "llm:" + str(model_id))
    row = await model_for_actor(db, actor, model_id)
    config = CatalogInput.model_validate(row.configuration)
    if not test and not visible(config, actor):
        fail(404, "model_unavailable", "模型未启用或未获授权")
    kind: OperationKind = (
        "transcription"
        if isinstance(body, TranscriptionInput)
        else "speech"
        if isinstance(body, SpeechInput)
        else "image_generation"
        if isinstance(body, ImageInput)
        else "chat"
        if isinstance(body, ChatInput)
        else "embedding"
        if isinstance(body, EmbeddingInput)
        else "rerank"
    )
    operation = config.for_operation(kind)
    if body.model != config.slug or operation is None:
        fail(422, "model_kind_mismatch", "模型标识或用途与调用接口不符")
    config = operation
    if config.gateway:
        from app.modules.model_gateway.capabilities import effective

        config = await effective(request, actor.tenant.id, config)
    if not test and not visible(config, actor):
        fail(404, "model_unavailable", "此操作未开放或未获授权")
    fingerprint = None
    if not test:
        if request.headers.get("idempotency-key") is not None:
            settings = provider(request).settings
            if settings.session_encryption_key is None:
                fail(503, "idempotency_unavailable", "请求幂等服务尚未配置")
            try:
                fingerprint = request_fingerprint(
                    settings, actor.tenant.id, actor.member.id, model_id, kind, body
                )
            except ValueError:
                fail(422, "invalid_request_identity", "请求参数不能生成稳定的幂等标识")
        await settlement.check_request(
            db, actor, request.headers.get("idempotency-key"), fingerprint
        )
    # Validate user input before claiming a circuit probe or creating a call record.
    if isinstance(body, TranscriptionInput):
        sdk_transcription.prepare(body, config.transcription)
    elif isinstance(body, SpeechInput):
        sdk_speech.prepare(body, config.speech, "validation")
    elif isinstance(body, ImageInput):
        sdk_images.prepare(body, config.image, "validation")
    elif isinstance(body, ChatInput):
        if (
            config.context_window
            and config.max_output
            and (body.actvero is not None or config.chat_policy != type(config.chat_policy)())
        ):
            from app.modules.llm.chat_policy import resolve

            body = resolve(body, config, row.version)
        else:
            chat.prepare(body, config, None)
    else:
        retrieval.prepare(body, config.retrieval, "validation")
    if isinstance(body, ChatInput) and config.routing.mode == "fixed":
        targets = await routing.channels_for(db, actor.tenant.id, config)
        for binding in config.bindings:
            if (binding.channel_id, binding.upstream_id) == (
                config.access.channel_id,
                config.access.upstream_id,
            ):
                channel = targets.get(binding.channel_id)
                if channel and channel.provider in PROVIDERS:
                    chat.prepare(body, config, binding, PROVIDERS[channel.provider].sdk_provider)
    if specific and not test:
        fail(403, "route_override_denied", "客户端不可指定上游渠道")
    from app.modules.llm import sdk_execution

    channels = await routing.channels_for(db, actor.tenant.id, config)
    pool = sdk_execution.candidates(
        request, actor.tenant.id, model_id, row.version, config, channels, body, specific
    )
    if config.gateway:
        from app.modules.model_gateway.execution import prepare

        await prepare(request, actor.tenant.id, config, pool)
    log = ModelCall(
        id=uuid4(),
        tenant_id=actor.tenant.id,
        model_id=model_id,
        channel_id=UUID(pool[0].evidence["channel_id"]),
        actor_id=actor.user.id,
        device_id=actor.device.id if isinstance(actor, NativeActor) else None,
        access_key_id=actor.key.id if isinstance(actor, keys.KeyActor) else None,
        source="admin_channel_test"
        if specific
        else "admin_route_test"
        if test
        else "access_key"
        if isinstance(actor, keys.KeyActor)
        else "desktop",
        kind=kind,
        attempts=[],
        prices=pool[0].evidence["prices"],
        status="pending",
    )
    db.add(log)
    if isinstance(actor, keys.KeyActor):
        actor.key.last_used_at = now()
    if not test:
        gateway_quote = None
        if config.gateway:
            from app.modules.model_gateway.admission import estimate

            gateway_quote = await estimate(request, actor.tenant.id, config, body)
        await settlement.reserve(
            db,
            actor,
            log,
            config,
            body,
            request.headers.get("idempotency-key"),
            request_fingerprint=fingerprint,
            gateway_quote=gateway_quote,
        )
    # The dispatch intent survives a crash immediately after admission commits.
    # The worker never replays a model request; unresolved intents become review.
    try:
        await request.app.state.llm_outbox.checkpoint(
            {
                "call_id": str(log.id),
                "tenant_id": str(log.tenant_id),
                "complete": False,
                "expires_at": time.time() + config.routing.total_timeout_seconds + 30,
                "attempts": [],
                "status": "pending",
                "delivered": False,
                "usage": {},
                "estimates": {},
            },
            required=True,
        )
    except OSError:
        fail(503, "accounting_unavailable", "调用凭证暂时无法持久保存，请稍后重试")
    await db.commit()  # Authorization, idempotency and quota admission are durable.
    async with aclosing(
        sdk_execution.execute(request, db, log, config, body, pool, test=test)
    ) as execution:
        async for output in execution:
            yield output


async def check_live(
    request: Request,
    db: AsyncSession,
    model_id: UUID,
    version: int,
    channel_id: UUID,
    channel_version: int,
    test: bool,
    kind: OperationKind = "chat",
    *,
    binding_id: UUID | None = None,
) -> None:
    actor = (
        await administrator(request, db)
        if test
        else await authorize(request, db, "llm:" + str(model_id), in_flight=True)
    )
    row = await model_for_actor(db, actor, model_id)
    config = CatalogInput.model_validate(row.configuration).for_operation(kind)
    channel = await db.get(ModelChannel, channel_id, populate_existing=True)
    if not test and (config is None or not visible(config, actor)):
        fail(404, "model_unavailable", "模型授权已变化")
    if channel is None or channel.archived or (not test and channel.manual_enabled is False):
        fail(403, "channel_disabled", "调用渠道已停用")
    if (
        not test
        and config is not None
        and not any(
            b.channel_id == channel_id
            and b.enabled
            and (binding_id is None or b.binding_id == binding_id)
            for b in config.bindings
        )
    ):
        fail(403, "route_disabled", "模型渠道绑定已停用")
    # Descriptive/price/parameter edits apply to the next admitted request.
    # This request retains its original configuration and price snapshot.


async def invoke(
    request: Request,
    db: AsyncSession,
    model_id: UUID,
    body: EmbeddingInput | RerankInput,
    *,
    test: bool = False,
    specific: tuple[UUID, str] | None = None,
) -> EmbeddingOutput | RerankOutput:
    async for output in execute(request, db, model_id, body, test=test, specific=specific):
        assert isinstance(output, (EmbeddingOutput, RerankOutput))
        return output
    raise AssertionError("missing inference output")
