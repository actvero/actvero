"""Read-only projection of the public protocols this platform actually serves."""

from collections.abc import Mapping
from typing import Literal, cast
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.llm import routing
from app.modules.llm.catalog_schemas import (
    CatalogInput,
    Declaration,
    EndpointSummary,
    OperationKind,
)
from app.modules.llm.models import CatalogModel, ModelChannel, RouteHealth
from app.modules.llm.providers import PROVIDERS

Reason = Literal[
    "operation_not_configured",
    "model_archived",
    "model_closed",
    "operation_closed",
    "no_binding",
    "fixed_target_unset",
    "binding_closed",
    "manual_disabled",
    "channel_missing",
    "channel_archived",
    "source_missing",
    "api_not_declared",
    "provider_unsupported",
    "credentials_required",
    "route_unverified",
    "route_incompatible",
    "route_cooldown",
    "route_probing",
    "credential_error",
    "model_error",
    "binding_error",
    "route_unavailable",
    "budget_price_missing",
]

PATHS: dict[OperationKind, str] = {
    "chat": "/api/llm/v1/chat/completions",
    "embedding": "/api/llm/v1/embeddings",
    "rerank": "/api/llm/v1/rerank",
    "image_generation": "/api/llm/v1/images/generations",
    "speech": "/api/llm/v1/audio/speech",
    "transcription": "/api/llm/v1/audio/transcriptions",
}
APIS = {
    "chat": "chat_completions",
    "embedding": "embeddings",
    "rerank": "rerank",
    "image_generation": "images",
    "speech": "speech",
    "transcription": "transcriptions",
}


class ClientEndpoint(BaseModel):
    operation: OperationKind
    method: Literal["POST"] = "POST"
    path: str
    inbound_protocol: Literal["openai_compatible"] = "openai_compatible"
    stream: bool
    tools: bool
    stream_declaration: Declaration | None = None
    tools_declaration: Declaration | None = None
    open: bool
    reasons: list[Reason] = Field(default_factory=list)
    example: dict[str, object]


class ModelEndpoints(BaseModel):
    model_id: UUID
    version: int
    slug: str
    member_authorization: Literal["not_evaluated"] = "not_evaluated"
    endpoints: list[ClientEndpoint]


def summarize_endpoints(projection: ModelEndpoints) -> EndpointSummary:
    configured = [
        item for item in projection.endpoints if "operation_not_configured" not in item.reasons
    ]
    return EndpointSummary(
        configured_count=len(configured),
        ready_count=sum(item.open for item in configured),
        reasons=list(dict.fromkeys(reason for item in configured for reason in item.reasons)),
    )


def _example(kind: OperationKind, slug: str) -> dict[str, object]:
    if kind == "chat":
        return {"model": slug, "messages": [{"role": "user", "content": "你好"}]}
    if kind == "embedding":
        return {"model": slug, "input": "示例文本"}
    if kind == "rerank":
        return {"model": slug, "query": "示例问题", "documents": ["示例文档"]}
    if kind == "speech":
        return {"model": slug, "input": "示例语音"}
    if kind == "transcription":
        return {"model": slug, "file": "<PCM WAV file>"}
    return {"model": slug, "prompt": "示例图片"}


def _binding_reasons(
    kind: OperationKind, binding: object, channel: ModelChannel | None
) -> list[Reason]:
    from app.modules.llm.catalog_schemas import ModelBinding

    assert isinstance(binding, ModelBinding)
    reasons: list[Reason] = []
    if not binding.enabled:
        reasons.append("binding_closed")
    if channel is None:
        return [*reasons, "channel_missing"]
    if channel.archived:
        reasons.append("channel_archived")
    if getattr(channel, "manual_enabled", None) is False:
        reasons.append("manual_disabled")
    if not any(item["id"] == binding.upstream_id for item in channel.models):
        reasons.append("source_missing")
    if APIS[kind] not in channel.declared_apis:
        reasons.append("api_not_declared")
    provider = PROVIDERS.get(channel.provider)
    if (
        provider is None
        or not provider.info.member_inference
        or kind not in provider.info.member_operations
    ):
        reasons.append("provider_unsupported")
    if channel.auth_mode == "api_key" and not channel.sealed_key:
        reasons.append("credentials_required")
    return reasons


async def project_endpoints(
    db: AsyncSession,
    tenant_id: UUID,
    row: CatalogModel,
    config: CatalogInput,
    channels: dict[UUID, ModelChannel],
    *,
    health_snapshot: Mapping[str, RouteHealth] | None = None,
) -> ModelEndpoints:
    """Read route state without choosing, claiming or sending to an upstream."""
    endpoints: list[ClientEndpoint] = []
    by_kind = {operation.kind: operation for operation in config.operation_configs()}
    for kind, path in PATHS.items():
        operation = by_kind.get(kind)
        reasons: list[Reason] = []
        if operation is None:
            reasons.append("operation_not_configured")
        else:
            if row.archived:
                reasons.append("model_archived")
            if not config.access.enabled:
                reasons.append("model_closed")
            if not operation.enabled:
                reasons.append("operation_closed")
            if not operation.bindings:
                reasons.append("no_binding")
            if operation.budget_price is None:
                reasons.append("budget_price_missing")
            scoped = operation.bindings
            if operation.routing.mode == "fixed":
                if not operation.channel_id or not operation.upstream_id:
                    reasons.append("fixed_target_unset")
                scoped = [
                    binding
                    for binding in scoped
                    if binding.channel_id == operation.channel_id
                    and binding.upstream_id == operation.upstream_id
                ]
                if operation.bindings and not scoped:
                    reasons.append("route_unavailable")
            candidate_reasons: list[list[Reason]] = []
            execution = config.for_operation(kind)
            assert execution is not None
            for binding in scoped:
                channel = channels.get(binding.channel_id)
                item_reasons = _binding_reasons(kind, binding, channel)
                if not item_reasons:
                    state, _ = await routing.state(
                        db,
                        tenant_id,
                        row.id,
                        execution,
                        binding,
                        channel,
                        require_test=operation.routing.mode == "auto",
                        health_snapshot=health_snapshot,
                    )
                    if state != "ready":
                        item_reasons.append(
                            cast(
                                Reason,
                                {
                                    "unverified": "route_unverified",
                                    "incompatible": "route_incompatible",
                                    "cooldown": "route_cooldown",
                                    "probing": "route_probing",
                                    "credential_error": "credential_error",
                                    "model_error": "model_error",
                                    "binding_error": "binding_error",
                                }.get(state, "route_unavailable"),
                            )
                        )
                candidate_reasons.append(item_reasons)
            if candidate_reasons and all(candidate_reasons):
                reasons.extend(
                    dict.fromkeys(reason for group in candidate_reasons for reason in group)
                )
        endpoints.append(
            ClientEndpoint(
                operation=kind,
                path=path,
                stream=kind == "chat"
                and bool(operation and operation.capabilities.streaming != "unsupported"),
                tools=kind == "chat"
                and bool(operation and operation.capabilities.tools != "unsupported"),
                stream_declaration=(
                    operation.capabilities.streaming if kind == "chat" and operation else None
                ),
                tools_declaration=(
                    operation.capabilities.tools if kind == "chat" and operation else None
                ),
                open=not reasons,
                reasons=reasons,
                example=_example(kind, config.slug),
            )
        )
    return ModelEndpoints(
        model_id=row.id, version=row.version, slug=config.slug, endpoints=endpoints
    )
