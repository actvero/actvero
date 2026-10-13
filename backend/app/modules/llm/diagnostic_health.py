"""Explicit, binding-scoped health certification for administrator diagnostics.

The caller commits the claimed lease together with its pending ModelCall before
issuing one SDK request.  Finish/release may run in a fresh database session.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now
from app.modules.desktop.errors import fail
from app.modules.llm import routing
from app.modules.llm.catalog_schemas import CatalogInput, ModelBinding, OperationKind
from app.modules.llm.models import CatalogModel, ModelChannel, RouteHealth
from app.modules.llm.schemas import (
    ChannelChatProbe,
    ChannelEmbeddingProbe,
    ChannelImageProbe,
    ChannelProbe,
    ChannelRerankProbe,
    ChannelTestView,
)
from app.modules.members.models import Membership
from app.modules.tenants.models import Tenant


@dataclass(frozen=True, slots=True)
class RecoveryLease:
    tenant_id: UUID
    actor_member_id: UUID
    model_id: UUID
    model_version: int
    binding_id: UUID
    channel_id: UUID
    channel_version: int
    operation: OperationKind
    upstream_id: str
    health_key: str
    fingerprint: str
    credential_fingerprint: str
    health_generation: int
    credential_generation: int
    probe_until: datetime
    expected_count: int | None = None
    expected_document_count: int | None = None
    expected_dimensions: int | None = None
    expected_image_size: str | None = None


def _binding(
    config: CatalogInput, binding_id: UUID, channel_id: UUID, upstream_id: str
) -> ModelBinding:
    matches = [binding for binding in config.bindings if binding.binding_id == binding_id]
    if (
        len(matches) != 1
        or matches[0].channel_id != channel_id
        or matches[0].upstream_id != upstream_id
    ):
        fail(409, "binding_changed", "指定绑定已变化，请刷新后重试")
    return matches[0]


def _expectations(
    config: CatalogInput, body: ChannelProbe
) -> tuple[int | None, int | None, str | None]:
    if isinstance(body, ChannelEmbeddingProbe):
        space = config.retrieval.embedding_space.strip()
        if not space:
            fail(409, "embedding_space_required", "请先配置向量空间后再认证绑定")
        dimensions = body.dimensions or config.retrieval.dimensions
        allowed = config.retrieval.dimension_options or (
            [config.retrieval.dimensions] if config.retrieval.dimensions else []
        )
        if dimensions is None or dimensions not in allowed:
            fail(422, "invalid_recovery_dimensions", "测试维度须符合模型操作配置")
        if len(body.input) > config.retrieval.max_batch_size or any(
            len(value) > config.retrieval.max_input_characters for value in body.input
        ):
            fail(422, "invalid_recovery_input", "测试输入超过模型操作限制")
        return len(body.input), dimensions, None
    if isinstance(body, ChannelRerankProbe):
        if len(body.documents) > config.retrieval.max_batch_size or any(
            len(value) > config.retrieval.max_input_characters
            for value in [body.query, *body.documents]
        ):
            fail(422, "invalid_recovery_input", "测试输入超过模型操作限制")
        return body.top_n or len(body.documents), None, None
    if isinstance(body, ChannelImageProbe):
        if (
            body.size != config.image.size
            or body.quality != config.image.quality
            or len(body.prompt) > config.image.max_prompt_characters
        ):
            fail(422, "invalid_recovery_image", "图片测试参数须与模型操作配置一致")
        return 1, None, body.size
    if isinstance(body, ChannelChatProbe):
        if config.max_output is not None and body.max_output_tokens > config.max_output:
            fail(422, "invalid_recovery_output", "测试输出上限超过模型操作配置")
        return None, None, None
    fail(422, "unsupported_recovery_operation", "此操作暂不可用于恢复绑定")


def _result_valid(lease: RecoveryLease, result: ChannelTestView | None) -> bool:
    if result is None or not result.ok or result.operation != lease.operation:
        return False
    if lease.operation == "embedding":
        indices = {vector.index for vector in result.vectors}
        return bool(
            len(result.vectors) == lease.expected_count
            and indices == set(range(lease.expected_count or 0))
            and all(vector.dimensions == lease.expected_dimensions for vector in result.vectors)
        )
    if lease.operation == "rerank":
        return (
            len(result.ranks) == lease.expected_count
            and len({rank.index for rank in result.ranks}) == len(result.ranks)
            and all(0 <= rank.index < (lease.expected_document_count or 0) for rank in result.ranks)
        )
    if lease.operation == "image_generation":
        if result.image_count != 1 or result.image is None:
            return False
        if lease.expected_image_size and lease.expected_image_size != "auto":
            width, height = (int(value) for value in lease.expected_image_size.split("x"))
            return (result.image.width, result.image.height) == (width, height)
    return True


async def _tenant_lock(db: AsyncSession, tenant_id: UUID) -> None:
    if await db.scalar(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()) is None:
        fail(404, "organization_unavailable", "组织不存在")


async def begin_recovery(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    actor_member_id: UUID,
    model_id: UUID,
    model_version: int,
    binding_id: UUID,
    channel_id: UUID,
    channel_version: int,
    body: ChannelProbe,
    stream: bool = False,
) -> RecoveryLease:
    """Claim one binding probe under a tenant lock; caller commits before I/O."""
    await _tenant_lock(db, tenant_id)
    member = await db.get(Membership, actor_member_id, populate_existing=True)
    if (
        member is None
        or member.tenant_id != tenant_id
        or member.status != "active"
        or member.role != "administrator"
    ):
        fail(403, "administrator_revoked", "管理员权限已变化")
    model = await db.get(CatalogModel, model_id, populate_existing=True)
    if model is None or model.tenant_id != tenant_id or model.archived:
        fail(404, "model_unavailable", "模型不存在或已归档")
    if model.version != model_version:
        fail(409, "model_changed", "模型配置已变化，请刷新后重试")
    if not isinstance(
        body,
        (ChannelChatProbe, ChannelEmbeddingProbe, ChannelRerankProbe, ChannelImageProbe),
    ):
        fail(422, "unsupported_recovery_operation", "此操作暂不可用于恢复绑定")
    config = CatalogInput.model_validate(model.configuration).for_operation(body.operation)
    if config is None:
        fail(409, "operation_changed", "模型未配置此操作")
    binding = _binding(config, binding_id, channel_id, body.id)
    channel = await db.get(ModelChannel, channel_id, populate_existing=True)
    if channel is None or channel.tenant_id != tenant_id or channel.archived:
        fail(409, "channel_unavailable", "渠道不存在或已归档")
    if channel.version != channel_version or body.version != channel_version:
        fail(409, "channel_changed", "渠道配置已变化，请刷新后重试")
    if not routing.available(
        config, binding, channel, allow_disabled=True, ignore_manual_enabled=True
    ):
        fail(409, "route_unavailable", "指定绑定的渠道、库存或接口已不可测试")
    if (
        isinstance(body, ChannelEmbeddingProbe)
        and binding.compatibility_key != config.retrieval.embedding_space
    ):
        fail(409, "embedding_space_mismatch", "绑定向量空间与模型操作不一致")
    expected_count, expected_dimensions, expected_image_size = _expectations(config, body)
    key = routing.health_key(tenant_id, model_id, config.kind, binding)
    fp = routing.fingerprint(config, binding, channel)
    health = await db.get(RouteHealth, key, populate_existing=True)
    current_time = now()
    if (
        health
        and health.fingerprint == fp
        and health.probe_until
        and health.probe_until > current_time
    ):
        fail(409, "route_probe_in_progress", "该绑定正在测试或恢复，请稍后重试")
    health = await routing.ensure(db, tenant_id, key, fp)
    lease_until = current_time + timedelta(
        seconds=min(channel.timeout_seconds, config.routing.total_timeout_seconds) + 5
    )
    if health.probe_until == lease_until:
        lease_until += timedelta(microseconds=1)
    health.probe_until = lease_until
    routing.advance(health)
    credential_fp = routing.credential_fingerprint(channel)
    credentials = await db.get(RouteHealth, routing.credential_key(channel), populate_existing=True)
    await db.flush()
    return RecoveryLease(
        tenant_id=tenant_id,
        actor_member_id=actor_member_id,
        model_id=model_id,
        model_version=model_version,
        binding_id=binding_id,
        channel_id=channel_id,
        channel_version=channel_version,
        operation=config.kind,
        upstream_id=body.id,
        health_key=key,
        fingerprint=fp,
        credential_fingerprint=credential_fp,
        health_generation=health.health_generation,
        credential_generation=(
            credentials.health_generation
            if credentials and credentials.fingerprint == credential_fp
            else 0
        ),
        probe_until=lease_until,
        expected_count=expected_count,
        expected_document_count=(
            len(body.documents) if isinstance(body, ChannelRerankProbe) else None
        ),
        expected_dimensions=expected_dimensions,
        expected_image_size=expected_image_size,
    )


async def _owned_health(db: AsyncSession, lease: RecoveryLease) -> RouteHealth | None:
    row = await db.get(RouteHealth, lease.health_key, populate_existing=True)
    return (
        row
        if row
        and row.probe_until == lease.probe_until
        and row.health_generation == lease.health_generation
        else None
    )


async def release_recovery(db: AsyncSession, lease: RecoveryLease) -> None:
    """Release only our probe; a later holder's lease must survive cancellation."""
    await _tenant_lock(db, lease.tenant_id)
    health = await _owned_health(db, lease)
    if health is not None:
        health.probe_until = None
        routing.advance(health)
    await db.flush()


async def finish_recovery(
    db: AsyncSession,
    lease: RecoveryLease,
    *,
    result: ChannelTestView | None,
) -> bool:
    """Certify only if the same live binding, credential and lease still exist."""
    await _tenant_lock(db, lease.tenant_id)
    health = await _owned_health(db, lease)
    if health is None:
        return False
    current_time = now()
    if (
        not _result_valid(lease, result)
        or lease.probe_until <= current_time
        or health.health_generation != lease.health_generation
    ):
        health.probe_until = None
        routing.advance(health)
        await db.flush()
        return False
    member = await db.get(Membership, lease.actor_member_id, populate_existing=True)
    model = await db.get(CatalogModel, lease.model_id, populate_existing=True)
    channel = await db.get(ModelChannel, lease.channel_id, populate_existing=True)
    current = None
    binding = None
    if (
        model is not None
        and model.tenant_id == lease.tenant_id
        and not model.archived
        and model.version == lease.model_version
    ):
        current = CatalogInput.model_validate(model.configuration).for_operation(lease.operation)
        if current is not None:
            binding = next((b for b in current.bindings if b.binding_id == lease.binding_id), None)
    credentials = (
        await db.get(RouteHealth, routing.credential_key(channel), populate_existing=True)
        if channel
        else None
    )
    valid = bool(
        member
        and member.tenant_id == lease.tenant_id
        and member.status == "active"
        and member.role == "administrator"
        and current
        and binding
        and binding.channel_id == lease.channel_id
        and binding.upstream_id == lease.upstream_id
        and channel
        and channel.tenant_id == lease.tenant_id
        and not channel.archived
        and channel.version == lease.channel_version
        and routing.credential_fingerprint(channel) == lease.credential_fingerprint
        and (
            credentials is None
            or credentials.fingerprint != lease.credential_fingerprint
            or credentials.health_generation == lease.credential_generation
        )
        and routing.fingerprint(current, binding, channel) == lease.fingerprint
        and health.fingerprint == lease.fingerprint
        and not (health.cooldown_until and health.cooldown_until > current_time)
    )
    health.probe_until = None
    routing.advance(health)
    if not valid:
        await db.flush()
        return False
    health.failures = 0
    health.cooldown_until = None
    health.blocked = False
    health.block_reason = None
    health.tested_at = current_time
    routing.advance(health)
    assert channel is not None
    if credentials and credentials.fingerprint == lease.credential_fingerprint:
        credentials.blocked = False
        routing.advance(credentials)
    await db.flush()
    return True
