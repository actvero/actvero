"""Translate public management forms without maintaining a second channel registry."""

import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.model_gateway import client
from app.modules.model_gateway.models import GatewayDirectory
from app.modules.model_gateway.schemas import GatewayChannelInput, GatewayDirectoryView

CHANNEL_FIELDS = (
    "id",
    "name",
    "type",
    "base_url",
    "status",
    "models",
    "model_mapping",
    "group",
    "priority",
    "weight",
    "tag",
    "test_model",
    "auto_ban",
    "param_override",
    "status_code_mapping",
    "response_time",
    "test_time",
    "created_time",
    "balance",
    "used_quota",
)
MODEL_FIELDS = (
    "id",
    "model_name",
    "description",
    "icon",
    "tags",
    "vendor_id",
    "endpoints",
    "status",
    "sync_official",
    "name_rule",
    "created_time",
    "updated_time",
    "bound_channels",
    "enable_groups",
    "supported_endpoints",
    "quota_types",
    "matched_models",
    "matched_count",
    "has_metadata",
    "configured_channel_count",
    "square_state",
)


def object_value(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HTTPException(502, "模型网关返回的数据格式不兼容")
    return value


def channel_view(raw: Any) -> dict[str, Any]:
    row = object_value(raw)
    value = {k: row.get(k) for k in CHANNEL_FIELDS}
    value["revision"] = client.revision(value)
    return value


def model_view(raw: Any) -> dict[str, Any]:
    row = object_value(raw)
    value = {k: row.get(k) for k in MODEL_FIELDS}
    value["revision"] = client.revision({k: value[k] for k in MODEL_FIELDS[:12]})
    return value


def page_view(raw: Any, kind: str) -> dict[str, Any]:
    page = object_value(raw)
    items = page.get("items") or []
    if not isinstance(items, list):
        raise HTTPException(502, "模型网关返回的数据格式不兼容")
    convert = channel_view if kind == "channel" else model_view
    return {"items": [convert(row) for row in items], "total": page.get("total", 0)}


def channel_payload(body: GatewayChannelInput) -> dict[str, Any]:
    value = body.model_dump(exclude={"revision", "key", "groups", "models", "model_mapping"})
    value.update(
        models=",".join(body.models),
        model_mapping=json.dumps(body.model_mapping, ensure_ascii=False),
        group=",".join(body.groups),
    )
    if body.key is not None and body.key.get_secret_value():
        value["key"] = body.key.get_secret_value()
    return value


async def get_channel(request: Request, tenant_id: UUID, channel_id: int) -> dict[str, Any]:
    if channel_id < 1:
        raise HTTPException(404, "渠道不存在")
    return object_value(await client.call(request, tenant_id, "GET", f"/api/channel/{channel_id}"))


def check_revision(current: dict[str, Any], expected: str | None) -> None:
    if not expected or current["revision"] != expected:
        raise HTTPException(409, "配置已变更，请刷新后重试")


async def invalidate_directory(db: AsyncSession, tenant_id: UUID, channel_id: int) -> None:
    await db.execute(
        delete(GatewayDirectory).where(
            GatewayDirectory.tenant_id == tenant_id, GatewayDirectory.channel_id == channel_id
        )
    )


async def directory(
    request: Request, db: AsyncSession, tenant_id: UUID, channel_id: int
) -> GatewayDirectoryView:
    raw = await get_channel(request, tenant_id, channel_id)
    row = await db.get(GatewayDirectory, (tenant_id, channel_id))
    config = await client.relay_connection(request, tenant_id)
    if (
        row is None
        or row.connection_id != client.connection_id(config)
        or row.channel_snapshot != directory_identity(raw)
    ):
        return GatewayDirectoryView(models=[])
    return GatewayDirectoryView(models=row.models, fetched_at=row.fetched_at)


def directory_identity(raw: dict[str, Any]) -> dict[str, Any]:
    return {k: raw.get(k) for k in ("type", "base_url", "created_time")}


async def all_channels(request: Request, tenant_id: UUID) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 51):
        result = object_value(
            await client.call(
                request, tenant_id, "GET", "/api/channel/", params={"p": page, "page_size": 100}
            )
        )
        rows.extend(channel_view(row) for row in result.get("items", []))
        if len(rows) >= result.get("total", 0):
            return rows
    raise HTTPException(422, "渠道数量超过本次映射查询上限，请缩小查询范围")
