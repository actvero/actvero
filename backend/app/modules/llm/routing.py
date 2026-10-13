"""Business eligibility and historical diagnostic records; dispatch belongs to LiteLLM."""

import hashlib
import json
from collections.abc import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.desktop.errors import fail
from app.modules.llm.catalog_schemas import CatalogInput, ModelBinding
from app.modules.llm.models import ModelChannel, RouteHealth
from app.modules.llm.providers import PROVIDERS


def advance(row: RouteHealth) -> None:
    """Monotone evidence revision; a stale success may never erase a later failure."""
    row.health_generation += 1


def hash_value(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def health_key(tenant_id: UUID, model_id: UUID, kind: str, binding: ModelBinding) -> str:
    return hash_value([tenant_id, model_id, kind, binding.channel_id, binding.upstream_id])


def credential_key(channel: ModelChannel) -> str:
    return hash_value([channel.tenant_id, "credentials", channel.id])


def credential_fingerprint(channel: ModelChannel) -> str:
    return hash_value([channel.base_url, channel.auth_mode, channel.sealed_key])


def fingerprint(config: CatalogInput, binding: ModelBinding, channel: ModelChannel) -> str:
    options = binding.chat_options.model_dump()
    if not any(v is not None for v in options["limits"].values()):
        options.pop("limits")  # Preserve existing certificates when no new constraints exist.
    return hash_value(
        [
            config.kind,
            config.retrieval.model_dump(),
            config.capabilities.model_dump() if config.kind == "chat" else None,
            [o.model_dump() for o in config.reasoning_options] if config.kind == "chat" else None,
            options if config.kind == "chat" else None,
            (config.context_window, config.max_output) if config.kind == "chat" else None,
            config.routing.model_revision,
            binding.compatibility_key,
            binding.upstream_id,
            getattr(channel, "routing_version", None) or channel.version,
            credential_fingerprint(channel),
        ]
        + ([config.image.model_dump()] if config.kind == "image_generation" else [])
        + ([config.speech.model_dump()] if config.kind == "speech" else [])
        + ([config.transcription.model_dump()] if config.kind == "transcription" else [])
    )


def available(
    config: CatalogInput,
    binding: ModelBinding,
    channel: ModelChannel | None,
    *,
    allow_disabled: bool = False,
    ignore_manual_enabled: bool = False,
) -> bool:
    return bool(
        (binding.enabled or allow_disabled)
        and (
            config.kind != "embedding"
            or config.routing.mode != "auto"
            or binding.compatibility_key == config.retrieval.embedding_space
        )
        and channel
        and channel.provider in PROVIDERS
        and PROVIDERS[channel.provider].info.member_inference
        and config.kind in PROVIDERS[channel.provider].info.member_operations
        and not channel.archived
        and (ignore_manual_enabled or getattr(channel, "manual_enabled", None) is not False)
        and any(m["id"] == binding.upstream_id for m in channel.models)
        and {
            "chat": "chat_completions",
            "embedding": "embeddings",
            "rerank": "rerank",
            "image_generation": "images",
            "speech": "speech",
            "transcription": "transcriptions",
        }[config.kind]
        in channel.declared_apis
        and (channel.auth_mode != "api_key" or channel.sealed_key)
    )


def configured_candidates(
    config: CatalogInput, channels: dict[UUID, ModelChannel]
) -> list[tuple[ModelBinding, ModelChannel]]:
    result = [
        (b, channels[b.channel_id])
        for b in config.bindings
        if available(config, b, channels.get(b.channel_id))
        and (
            config.routing.mode != "fixed"
            or (b.channel_id, b.upstream_id)
            == (config.access.channel_id, config.access.upstream_id)
        )
    ]
    if not result:
        fail(409, "route_unavailable", "没有已启用且获准调用的渠道")
    return result


async def channels_for(
    db: AsyncSession, tenant_id: UUID, config: CatalogInput
) -> dict[UUID, ModelChannel]:
    rows = await db.scalars(
        select(ModelChannel)
        .where(
            ModelChannel.tenant_id == tenant_id,
            ModelChannel.id.in_([b.channel_id for b in config.bindings]),
        )
        .execution_options(populate_existing=True)
    )
    return {r.id: r for r in rows}


async def state(
    db: AsyncSession,
    tenant_id: UUID,
    model_id: UUID,
    config: CatalogInput,
    binding: ModelBinding,
    channel: ModelChannel | None,
    *,
    require_test: bool,
    ignore_manual_enabled: bool = False,
    health_snapshot: Mapping[str, RouteHealth] | None = None,
) -> tuple[str, RouteHealth | None]:
    if not binding.enabled:
        return "disabled", None
    if (
        channel is not None
        and getattr(channel, "manual_enabled", None) is False
        and not ignore_manual_enabled
        and not channel.archived
    ):
        return "manual_disabled", None
    if not available(config, binding, channel, ignore_manual_enabled=ignore_manual_enabled):
        return "unavailable", None
    # Runtime eligibility is business configuration only. Historical certificates,
    # byte estimates and the former database circuit cannot veto SDK dispatch.
    # Actual provider availability is decided by LiteLLM at invocation time.
    return "ready", None


async def ensure(db: AsyncSession, tenant_id: UUID, key: str, fp: str) -> RouteHealth:
    # Callers hold the tenant row lock. No network I/O while holding this lock.
    row = await db.get(RouteHealth, key, populate_existing=True)
    if row is None:
        row = RouteHealth(id=key, tenant_id=tenant_id, fingerprint=fp, failures=0, blocked=False)
        db.add(row)
    elif row.fingerprint != fp:
        row.fingerprint = fp
        row.tested_at = row.cooldown_until = row.probe_until = None
        row.failures, row.blocked = 0, False
        row.block_reason = None
        advance(row)
    await db.flush()
    return row
