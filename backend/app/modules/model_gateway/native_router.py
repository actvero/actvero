"""Native channel forms behind Actvero organization authorization."""

import json
import re
from typing import Annotated, Any, Literal
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from app.modules.auth.service import DB
from app.modules.members.service import record
from app.modules.model_gateway import client, native_models, service
from app.modules.model_gateway.authorization import administrator
from app.modules.model_gateway.router import audit, protect_mutation

router = APIRouter(
    prefix="/api/v1/model-gateway/native",
    tags=["model-gateway"],
    dependencies=[Depends(protect_mutation)],
)

READ_PATHS = {
    "api/channel/default_base_urls": "/api/channel/default_base_urls",
    "api/channel/models": "/api/channel/models",
    "api/group": "/api/group/",
    "api/prefill_group": "/api/prefill_group/",
    "api/task_plugin_options": "/api/task_plugin_options",
    "api/status": "/api/status",
    "api/notice": "/api/notice",
    "api/channel/ops": "/api/channel/ops",
}

EDIT_FIELDS = service.CHANNEL_FIELDS + (
    "openai_organization",
    "other",
    "setting",
    "settings",
    "header_override",
    "remark",
    "max_input_tokens",
    "balance_updated_time",
)
VOLATILE_FIELDS = {"response_time", "test_time", "balance", "used_quota", "balance_updated_time"}


def edit_view(raw: dict[str, Any]) -> dict[str, Any]:
    """Keep native form fields, while never exposing the stored channel key."""
    data = {key: raw.get(key) for key in EDIT_FIELDS}
    info = raw.get("channel_info") or {}
    data["channel_info"] = {
        "is_multi_key": info.get("is_multi_key", False),
        "multi_key_size": info.get("multi_key_size", 0),
        "multi_key_mode": info.get("multi_key_mode", "random"),
    }
    data["revision"] = client.revision(
        {key: value for key, value in data.items() if key not in VOLATILE_FIELDS}
    )
    data["key"] = ""
    return data


class NativeCreateInput(BaseModel):
    # The native frontend and New API validate the actual provider-specific
    # payload. This boundary limits size and allowed operation, without another
    # interpretation of credential formats, settings or multi-key modes.
    mode: Literal["single", "batch", "multi_to_single"]
    channel: dict[str, JsonValue] = Field(max_length=60)
    multi_key_mode: str | None = None
    batch_add_set_key_prefix_2_name: bool | None = None


class NativeUpdateInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, JsonValue] = Field(init=False)
    id: int = Field(gt=0, strict=True)


@router.get("/{path:path}", response_model=None)
async def native_read(
    request: Request, response: Response, db: DB, path: str
) -> dict[str, Any] | Response:
    actor = await administrator(request, db)
    path = path.rstrip("/")
    if native_models.can_read(path):
        response.headers["Cache-Control"] = "no-store"
        return await native_models.read(request, actor.tenant.id, path)
    if match := re.fullmatch(r"api/channel/([1-9][0-9]*)", path):
        raw = await service.get_channel(request, actor.tenant.id, int(match[1]))
        response.headers["Cache-Control"] = "no-store"
        return {"success": True, "data": edit_view(raw)}
    if re.fullmatch(r"api/plugin/task/[A-Za-z0-9_-]{1,100}/icon", path):
        icon = await client.send(request, actor.tenant.id, "GET", "/" + path)
        media = icon.headers.get("content-type", "").split(";")[0]
        if not icon.is_success or media not in {
            "image/svg+xml",
            "image/png",
            "image/jpeg",
            "image/webp",
        }:
            raise HTTPException(404, "插件图标不可用")
        return Response(
            icon.content,
            media_type=media,
            headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"},
        )
    target = READ_PATHS.get(path)
    if not target:
        raise HTTPException(404, "此网关操作尚未接入")
    params: dict[str, str | int] = dict(request.query_params)
    if path == "api/prefill_group":
        group_type = params.get("type", "model")
        params = {
            "type": group_type if group_type in {"group", "model", "tag", "endpoint"} else "model"
        }
    elif path == "api/channel/ops" and params.get("auto_ban") in {"true", "false"}:
        params = {"auto_ban": params["auto_ban"]}
    else:
        params = {}
    result = await client.call(request, actor.tenant.id, "GET", target, params=params)
    return {"success": True, "data": result}


@router.put("/api/channel/")
async def native_update(
    request: Request,
    db: DB,
    body: NativeUpdateInput,
    expected_revision: Annotated[str, Header(alias="If-Match", min_length=64, max_length=64)],
) -> dict[str, Any]:
    actor = await administrator(request, db, write=True)
    data = body.model_dump()
    if len(data) > 60 or len(json.dumps(data)) > 200000 or "status" in data:
        raise HTTPException(422, "渠道配置格式或大小不符合要求")
    current = await service.get_channel(request, actor.tenant.id, body.id)
    service.check_revision(edit_view(current), expected_revision)
    if not data.get("key"):
        data.pop("key", None)
    # Forward the native partial payload. Do not reconstruct settings or resend
    # a stored credential; New API owns provider validation and multi-key edits.
    await client.call(request, actor.tenant.id, "PUT", "/api/channel/", payload=data)
    if data.get("key") or any(
        key in data and data[key] != current.get(key)
        for key in ("type", "base_url", "other", "setting", "settings", "header_override")
    ):
        await service.invalidate_directory(db, actor.tenant.id, body.id)
    await audit(db, actor, "channel.update", str(body.id))
    return {"success": True}


@router.post("/api/channel")
async def native_create(request: Request, db: DB, body: NativeCreateInput) -> dict[str, Any]:
    actor = await administrator(request, db, write=True)
    data = body.model_dump(exclude_none=True)
    if len(json.dumps(data)) > 200000:
        raise HTTPException(422, "渠道配置超过大小上限")
    result = await client.call(request, actor.tenant.id, "POST", "/api/channel/", payload=data)
    record(
        db,
        actor,
        "model_gateway.channel.create",
        uuid5(NAMESPACE_URL, str(actor.tenant.id) + ":native-create"),
        "New API channel",
    )
    await db.commit()
    return {"success": True, "data": result}


@router.post("/api/channel/fetch_models")
async def native_discover(request: Request, db: DB, body: dict[str, JsonValue]) -> dict[str, Any]:
    actor = await administrator(request, db, write=True)
    if len(json.dumps(body)) > 200000 or len(body) > 20:
        raise HTTPException(422, "模型发现配置超过大小上限")
    # Only draft discovery is exposed in this block. Never accept an ID from
    # another registry as permission to read a stored supplier credential.
    body.pop("channel_id", None)
    data = await client.call(
        request, actor.tenant.id, "POST", "/api/channel/fetch_models", payload=body
    )
    return {"success": True, "data": data}


@router.post("/{path:path}", operation_id="model_gateway_native_model_post")
@router.put("/{path:path}", operation_id="model_gateway_native_model_put")
@router.patch("/{path:path}", operation_id="model_gateway_native_model_patch")
@router.delete("/{path:path}", operation_id="model_gateway_native_model_delete")
async def native_model_write(
    request: Request, db: DB, path: str, body: dict[str, JsonValue] | None = None
) -> dict[str, Any]:
    actor = await administrator(request, db, write=True)
    return await native_models.mutate(request, db, actor, path.rstrip("/"), body)
