"""Actvero access policy over a native model name; no duplicate supplier routes."""

import hashlib
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from app.modules.auth.service import DB, now, provider
from app.modules.llm.audio_schemas import SpeechOptions, TranscriptionOptions
from app.modules.llm.catalog_schemas import (
    CatalogInput,
    ChatPolicy,
    GatewayExecution,
    ModelAccess,
    ModelBinding,
    ModelCapabilities,
    OperationKind,
    ReasoningOption,
    RetrievalOptions,
)
from app.modules.llm.image_schemas import ImageOptions
from app.modules.llm.models import CatalogModel, ModelChannel
from app.modules.llm.schemas import Input
from app.modules.members.models import Membership
from app.modules.members.service import Access
from app.modules.model_gateway import client
from app.modules.tenants.models import Tenant


class PublicationInput(Input):
    model_name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,127}$")
    version: int = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=100)
    enabled: bool = False
    audience: str = Field(
        default="administrators", pattern=r"^(administrators|organization|selected)$"
    )
    member_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    kind: OperationKind = "chat"
    context_window: int | None = Field(default=None, ge=1, le=100000000)
    max_output: int | None = Field(default=None, ge=1, le=100000000)
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    reasoning_options: list[ReasoningOption] = Field(default_factory=list, max_length=3)
    retrieval: RetrievalOptions = Field(default_factory=RetrievalOptions)
    image: ImageOptions = Field(default_factory=ImageOptions)
    speech: SpeechOptions = Field(default_factory=SpeechOptions)
    transcription: TranscriptionOptions = Field(default_factory=TranscriptionOptions)
    capability_mode: Literal["auto", "manual"] = "auto"
    chat_policy: ChatPolicy = Field(default_factory=ChatPolicy)
    reserve_usd: str = Field(
        default="0.01",
        pattern=r"^(0|[1-9][0-9]{0,5})(\.[0-9]{1,8})?$",
        deprecated=True,
        description="Legacy compatibility field; reservations are calculated by New API.",
    )


def origin_hash(base: str) -> str:
    return hashlib.sha256(base.encode()).hexdigest()


async def find(db: DB, tenant_id: UUID, name: str) -> CatalogModel | None:
    row: CatalogModel | None = await db.scalar(
        select(CatalogModel).where(
            CatalogModel.tenant_id == tenant_id,
            CatalogModel.slug == name,
        )
    )
    return row


def view(row: CatalogModel | None) -> dict[str, Any]:
    if not row or not row.configuration.get("gateway"):
        return {"version": 0, "enabled": False}
    c = CatalogInput.model_validate(row.configuration)
    assert c.gateway is not None
    return {
        "id": str(row.id),
        "version": row.version,
        "model_name": row.slug,
        "name": row.name,
        "enabled": c.access.enabled and not row.archived,
        "audience": c.access.audience,
        "member_ids": [str(x) for x in c.access.member_ids],
        "reserve_usd": c.gateway.reserve_usd,
        "capability_mode": c.gateway.capability_mode,
        "capability_source": c.gateway.capability_source,
        **c.model_dump(
            mode="json",
            include={
                "kind",
                "chat_policy",
                "context_window",
                "max_output",
                "capabilities",
                "reasoning_options",
                "retrieval",
                "image",
                "speech",
                "transcription",
            },
        ),
    }


async def save(request: Request, db: DB, actor: Access, body: PublicationInput) -> CatalogModel:
    connection = await client.relay_connection(request, actor.tenant.id)
    # Serialize publication/inventory edits with ordinary quota admission.
    await db.scalar(select(Tenant.id).where(Tenant.id == actor.tenant.id).with_for_update())
    row = await find(db, actor.tenant.id, body.model_name)
    if row and not row.configuration.get("gateway"):
        raise HTTPException(409, "已有同名旧模型，请先为旧模型改名，再开放网关模型")
    if body.version != (row.version if row else 0):
        raise HTTPException(409, "成员访问配置已变化，请刷新后重试")
    if body.audience == "selected":
        members = set(
            await db.scalars(
                select(Membership.id).where(
                    Membership.tenant_id == actor.tenant.id,
                    Membership.status == "active",
                    Membership.id.in_(body.member_ids),
                )
            )
        )
        if not members or members != set(body.member_ids):
            raise HTTPException(422, "请选择本组织的有效成员")
    from app.modules.model_gateway.access_status import inspect

    status = (await inspect(request, db, actor, [body.model_name], body))[0]
    if body.enabled and not status.ready:
        raise HTTPException(409, next(c.message for c in status.checks if c.status != "ready"))
    auto = status.automatic
    body = apply_profile(body, auto)
    channel_id = uuid5(NAMESPACE_URL, f"actvero:newapi:{actor.tenant.id}")
    transport = await db.get(ModelChannel, channel_id)
    if transport is None:
        transport = ModelChannel(
            id=channel_id,
            tenant_id=actor.tenant.id,
            name="New API · 系统连接",
            provider="openai-compatible",
            base_url=connection.base_url + "/v1",
            auth_mode="api_key",
            models=[],
            routing={"engine": "newapi"},
            automatic_protection={"enabled": False},
            declared_apis=[
                "chat_completions",
                "embeddings",
                "rerank",
                "images",
                "speech",
                "transcriptions",
            ],
        )
        db.add(transport)
    transport.base_url = connection.base_url + "/v1"
    if connection.relay_key:
        transport.sealed_key = provider(request).seal(
            {"key": connection.relay_key.get_secret_value()}
        )
    if not any(m["id"] == body.model_name for m in transport.models):
        transport.models = [*transport.models, {"id": body.model_name}]
    await db.flush()
    config = configuration(actor.tenant.id, connection.base_url, body, auto)
    if row is None:
        row = CatalogModel(
            tenant_id=actor.tenant.id,
            slug=body.model_name,
            name=body.name,
            configuration=config.model_dump(mode="json"),
            version=1,
        )
        db.add(row)
    else:
        previous = CatalogInput.model_validate(row.configuration)
        if previous.kind == "embedding" and previous.retrieval != config.retrieval:
            # Keep issued resource identities tied to their vector space.
            raise HTTPException(409, "向量参数变更请使用新的模型名称")
        row.name, row.configuration = body.name, config.model_dump(mode="json")
        row.archived, row.updated_at = False, now()
        row.version += 1
    await db.flush()
    return row


def apply_profile(body: PublicationInput, auto: dict[str, Any]) -> PublicationInput:
    if body.kind != "chat" or body.capability_mode != "auto" or auto.get("status") != "resolved":
        return body
    values = {
        key: auto[key]
        for key in (
            "context_window",
            "max_output",
            "capabilities",
            "chat_policy",
            "reasoning_options",
        )
    }
    return PublicationInput.model_validate(body.model_dump() | values)


def resolve_body(
    body: PublicationInput, group: str, channels: list[dict[str, Any]]
) -> tuple[PublicationInput, dict[str, Any]]:
    from app.modules.model_gateway.capabilities import resolve

    automatic = (
        resolve(body.model_name, group, channels)
        if body.kind == "chat" and body.capability_mode == "auto"
        else {}
    )
    return apply_profile(body, automatic), automatic


def configuration(
    tenant_id: UUID, base_url: str, body: PublicationInput, auto: dict[str, Any]
) -> CatalogInput:
    channel_id = uuid5(NAMESPACE_URL, f"actvero:newapi:{tenant_id}")
    return CatalogInput(
        slug=body.model_name,
        name=body.name,
        **body.model_dump(
            exclude={
                "model_name",
                "version",
                "name",
                "enabled",
                "audience",
                "member_ids",
                "reserve_usd",
                "capability_mode",
            }
        ),
        gateway=GatewayExecution(
            origin_hash=origin_hash(base_url),
            reserve_usd=body.reserve_usd,
            capability_mode=body.capability_mode,
            capability_source=auto.get("source", {}),
        ),
        bindings=[ModelBinding(channel_id=channel_id, upstream_id=body.model_name, enabled=True)],
        access=ModelAccess(
            enabled=body.enabled,
            audience=body.audience,
            member_ids=body.member_ids,
            channel_id=channel_id,
            upstream_id=body.model_name,
        ),
    )
