"""Stateless Streamable HTTP JSON responses; no shared upstream identity/session cache."""

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from app.modules.access_keys import service as keys
from app.modules.auth.service import DB, now
from app.modules.desktop.errors import fail
from app.modules.desktop_mcp import service
from app.modules.desktop_mcp.router import RESOURCE
from app.modules.desktop_mcp.schemas import RpcRequest
from app.modules.mcp import service as mcp
from app.modules.mcp.schemas import McpRun

VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
router = APIRouter(prefix="/api/mcp/services", tags=["mcp-gateway"])


def rpc_error(
    id: str | int | None, code: int, message: str, reason: str, retry_after: int | None = None
) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": id,
            "error": {
                "code": code,
                "message": message,
                "data": {"code": reason, **({"retry_after": retry_after} if retry_after else {})},
            },
        }
    )


@router.api_route("/{service_id}", methods=["GET", "DELETE"], include_in_schema=False)
async def unsupported_stream(service_id: UUID, request: Request, db: DB) -> Response:
    if request.headers.get("origin"):
        fail(403, "origin_denied", "此入口仅接受原生客户端")
    actor = (
        await keys.authorize(request, db, "mcp", service_id)
        if keys.supplied(request)
        else await service.authorize(request, db, "mcp:" + str(service_id))
    )
    await service.get_service(db, actor, service_id)
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post(
    "/{service_id}",
    dependencies=RESOURCE,
    summary="调用标准 MCP 协议（Streamable HTTP）",
    description=(
        "接受含当前服务权限的个人访问密钥或单服务资源令牌；"
        "每次校验凭据、成员与能力授权。个人密钥不替代 MCP OAuth 授权流程。"
        "无状态 Streamable HTTP，返回 JSON；GET/DELETE 为 405。"
        "支持 initialize、ping、tools/list、tools/call、prompts/list、prompts/get、"
        "resources/list、resources/templates/list、resources/read。"
        "Accept 同时包含 application/json、text/event-stream；"
        "初始化后携带 MCP-Protocol-Version。"
        "不提供订阅、任务、补全、采样、推送或自动重试。"
        "详见 DSH-MCP-ACCESS.md 和 ACCESS-KEYS.md。"
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["jsonrpc", "method"],
                        "properties": {
                            "jsonrpc": {"const": "2.0"},
                            "id": {"type": ["string", "integer"]},
                            "method": {"type": "string"},
                            "params": {"type": "object"},
                        },
                    },
                    "example": {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                }
            },
        }
    },
    responses={
        202: {"description": "已接收通知，无响应体"},
        400: {"description": "协议版本或消息无效"},
        401: {"description": "访问密钥、资源令牌或设备失效"},
        403: {"description": "资源不匹配或成员失效"},
        404: {"description": "服务已关闭或撤权"},
        406: {"description": "Accept 需同时包含 application/json 和 text/event-stream"},
    },
)
async def protocol(service_id: UUID, request: Request, db: DB) -> Response:
    return await _protocol(service_id, request, db)


@router.post(
    "/{service_id}/experts/{expert_id}/releases/{release_id}/{connector_key}",
    dependencies=RESOURCE,
    summary="在确切专家发布的工具范围内调用 MCP",
    description="使用该连接器的 mcp:<服务ID> 令牌。继承原 MCP 协议与鉴权，"
    "逐次检查专家授权并过滤 tools/list、拒绝未选工具的 tools/call。"
    "发布新版本保留已有会话的工具范围；专家下架或撤权立即拒绝。",
)
async def expert_protocol(
    service_id: UUID,
    expert_id: UUID,
    release_id: UUID,
    connector_key: str,
    request: Request,
    db: DB,
) -> Response:
    return await _protocol(service_id, request, db, (expert_id, release_id, connector_key))


async def _protocol(
    service_id: UUID,
    request: Request,
    db: DB,
    expert_scope: tuple[UUID, UUID, str] | None = None,
) -> Response:
    if request.headers.get("origin"):
        fail(403, "origin_denied", "此入口仅接受原生客户端")
    actor = (
        await keys.authorize(request, db, "mcp", service_id)
        if keys.supplied(request)
        else await service.authorize(request, db, "mcp:" + str(service_id))
    )
    row = await service.get_service(db, actor, service_id)
    original_version = row.version
    action = "read"
    locked_ref = None
    tool_selection = None
    precise_scope = False
    unverified_new_scope = False
    if expert_scope:
        from app.modules.experts.connector_access import reference

        locked_ref = await reference(db, actor, service_id, *expert_scope)
        tool_selection = set(locked_ref["tools"]) if locked_ref.get("tools") is not None else None
        precise_scope = locked_ref.get("capability_contracts") is not None
        unverified_new_scope = locked_ref.get("reference_version") == 3 and not precise_scope

    async def guard(entry: dict[str, Any] | None) -> None:
        current_actor = (
            await keys.authorize(request, db, "mcp", service_id, action)
            if isinstance(actor, keys.KeyActor)
            else await service.authorize(request, db, "mcp:" + str(service_id))
        )
        current = await service.get_service(db, current_actor, service_id)
        if current.version != original_version:
            raise HTTPException(409, "连接器配置已变化，请重新读取后重试")
        if expert_scope:
            from app.modules.experts.connector_access import reference
            from app.modules.experts.connector_contracts import matches

            ref = await reference(db, current_actor, service_id, *expert_scope)
            if entry is not None and precise_scope:
                from app.modules.experts.connector_contracts import matches_v3

                mismatch = await matches_v3(db, current, ref, entry, entry.get("_protocol", ""))
                if mismatch:
                    error = HTTPException(
                        403 if mismatch == "not_selected" else 409,
                        f"专家能力 {entry['kind']}:{entry['key']} "
                        + (
                            "未包含在本发布中"
                            if mismatch == "not_selected"
                            else "定义已变化，请检查后发布新版本"
                        ),
                    )
                    error.code = (  # type: ignore[attr-defined]
                        "expert_capability_denied"
                        if mismatch == "not_selected"
                        else "expert_" + mismatch
                    )
                    raise error
            elif entry is not None and entry["kind"] == "tools" and not matches(ref, entry):
                raise HTTPException(409, "专家所选工具定义已变化，请检查依赖后发布新版本")
        if entry is not None:
            from app.modules.mcp.models import McpPolicy

            rule = await db.get(
                McpPolicy, (service_id, entry["kind"], entry["key"]), populate_existing=True
            )
            if not mcp.capability_allowed(rule, entry):
                raise HTTPException(403, "该能力当前未开放")

    accepts = {part.split(";")[0].strip() for part in request.headers.get("accept", "").split(",")}
    if not {"application/json", "text/event-stream"}.issubset(accepts):
        fail(406, "accept_required", "Accept 需包含 application/json 和 text/event-stream")
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        fail(415, "json_required", "请求体须为 application/json")
    version = request.headers.get("mcp-protocol-version", "2025-03-26")
    if version not in VERSIONS:
        fail(400, "unsupported_protocol", "不支持此 MCP 协议版本")
    if request.headers.get("mcp-session-id"):
        fail(404, "mcp_session_not_found", "此入口无状态，请重新初始化且不携带会话 ID")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 131072:
            fail(413, "request_too_large", "请求超过 128 KiB")
    try:
        decoded = json.loads(raw)
    except (ValueError, UnicodeError):
        return rpc_error(None, -32700, "JSON 解析失败", "parse_error")
    try:
        body = RpcRequest.model_validate(decoded)
        if "id" in decoded and (decoded["id"] is None or isinstance(decoded["id"], bool)):
            raise ValueError()
    except (ValidationError, ValueError):
        return rpc_error(None, -32600, "JSON-RPC 请求无效", "invalid_request")
    if "id" not in decoded:
        if body.method.startswith("notifications/"):
            return Response(status_code=202)
        return rpc_error(None, -32600, "请求缺少 id", "invalid_request")
    if unverified_new_scope and body.method not in {"initialize", "ping"}:
        return rpc_error(
            body.id, -32000, "此专家发布的连接器能力未核实，请联系管理员", "expert_unverified"
        )
    action = "invoke" if body.method == "tools/call" else "read"
    if isinstance(actor, keys.KeyActor):
        actor = await keys.authorize(request, db, "mcp", service_id, action)
        actor.key.last_used_at = now()
        await db.commit()
    p = body.params
    result: dict[str, Any]
    try:
        if body.method == "initialize":
            if (
                not isinstance(p.get("protocolVersion"), str)
                or not isinstance(p.get("clientInfo"), dict)
                or not isinstance(p.get("capabilities"), dict)
            ):
                return rpc_error(body.id, -32602, "初始化参数不完整", "invalid_params")
            result = {
                "protocolVersion": p["protocolVersion"]
                if p["protocolVersion"] in VERSIONS
                else VERSIONS[0],
                "serverInfo": {"name": "Actvero", "version": "1.0.0"},
                "capabilities": {"tools": {}, "prompts": {}, "resources": {}},
            }
        elif body.method == "ping":
            result = {}
        elif body.method in {
            "tools/list",
            "prompts/list",
            "resources/list",
            "resources/templates/list",
        }:
            if p.get("cursor"):
                return rpc_error(body.id, -32602, "此目录没有下一页", "invalid_cursor")
            caps = await mcp.refresh(request, db, row, actor, guard)
            kind, field = {
                "tools/list": ("tools", "tools"),
                "prompts/list": ("prompts", "prompts"),
                "resources/list": ("resources", "resources"),
                "resources/templates/list": ("templates", "resourceTemplates"),
            }[body.method]
            from app.modules.experts.connector_contracts import matches, matches_v3

            visible = []
            for c in caps.items:
                if c.kind != kind:
                    continue
                if kind == "tools" and tool_selection is not None and c.key not in tool_selection:
                    continue
                catalog_entry = {
                    "kind": c.kind,
                    "key": c.key,
                    "definition": c.definition,
                    "description": c.original_description,
                }
                if precise_scope and locked_ref is not None:
                    if await matches_v3(db, row, locked_ref, catalog_entry, caps.protocol):
                        continue
                elif (
                    kind == "tools"
                    and locked_ref is not None
                    and not matches(locked_ref, catalog_entry)
                ):
                    continue
                visible.append({**c.definition, "description": c.description})
            result = {field: visible}
        elif body.method in {"tools/call", "prompts/get"}:
            args = p.get("arguments", {})
            if not isinstance(p.get("name"), str) or not isinstance(args, dict):
                return rpc_error(body.id, -32602, "name 或 arguments 无效", "invalid_params")
            if (
                body.method == "tools/call"
                and tool_selection is not None
                and p["name"] not in tool_selection
            ):
                return rpc_error(body.id, -32000, "此专家未启用该工具", "expert_tool_denied")
            run = McpRun(
                kind="tools" if body.method == "tools/call" else "prompts",
                key=p["name"],
                arguments=args,
            )
            result = (await mcp.run(request, db, row, actor, run, guard)).result
        elif body.method == "resources/read":
            from fastmcp.resources.template import match_uri_template

            uri = p.get("uri")
            if not isinstance(uri, str) or len(uri) > 2000:
                return rpc_error(body.id, -32602, "uri 无效", "invalid_params")
            caps = await mcp.refresh(request, db, row, actor, guard)
            entry = next((c for c in caps.items if c.kind == "resources" and c.key == uri), None)
            if not entry:
                entry = next(
                    (
                        c
                        for c in caps.items
                        if c.kind == "templates" and match_uri_template(uri, c.key) is not None
                    ),
                    None,
                )
            if not entry:
                return rpc_error(body.id, -32002, "资源不存在或未开放", "resource_unavailable")
            if precise_scope and locked_ref is not None:
                from app.modules.experts.connector_contracts import matches_v3

                mismatch = await matches_v3(
                    db,
                    row,
                    locked_ref,
                    {
                        "kind": entry.kind,
                        "key": entry.key,
                        "definition": entry.definition,
                        "description": entry.original_description,
                    },
                    caps.protocol,
                )
                if mismatch:
                    return rpc_error(
                        body.id, -32000, "专家资源未获准或定义已变化", "expert_" + mismatch
                    )
            run = McpRun(kind=entry.kind, key=entry.key, uri=uri)
            result = (await mcp.run(request, db, row, actor, run, guard)).result
        else:
            return rpc_error(body.id, -32601, "不支持此 MCP 方法", "method_not_found")
        await guard(None)
        await db.commit()
        return JSONResponse({"jsonrpc": "2.0", "id": body.id, "result": result})
    except ValidationError:
        return rpc_error(body.id, -32602, "参数不符合要求", "invalid_params")
    except HTTPException as exc:
        reasons = {
            401: "resource_token_invalid",
            404: "resource_unavailable",
            403: "capability_denied",
            409: "connection_or_definition_changed",
            422: "invalid_params",
            502: "upstream_unavailable",
            503: "authorization_unavailable",
            504: "upstream_timeout",
        }
        return rpc_error(
            body.id,
            -32602 if exc.status_code == 422 else -32000,
            str(exc.detail),
            getattr(exc, "code", reasons.get(exc.status_code, "operation_failed")),
            getattr(exc, "seconds", None),
        )
