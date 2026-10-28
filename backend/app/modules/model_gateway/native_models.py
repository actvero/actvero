"""Native model metadata, vendor and price operations; no second registry."""

import json
import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import JsonValue
from sqlalchemy import select

from app.modules.auth.service import DB
from app.modules.members.service import Access
from app.modules.model_gateway import client, presentation, service
from app.modules.model_gateway.connection_templates import pricing_reference
from app.modules.model_gateway.router import audit
from app.modules.tenants.models import Tenant

READS = {
    "api/models": "/api/models/",
    "api/models/search": "/api/models/search",
    "api/models/missing": "/api/models/missing",
    "api/models/sync_upstream/preview": "/api/models/sync_upstream/preview",
    "api/vendors": "/api/vendors/",
    "api/vendors/search": "/api/vendors/search",
    "api/option/model_pricing": "/api/option/model_pricing",
    "api/ratio_sync/channels": "/api/ratio_sync/channels",
    "api/pricing": "/api/pricing",
}
QUERY_FIELDS = {
    "p",
    "page_size",
    "keyword",
    "vendor",
    "status",
    "sync_official",
    "include_channel_models",
    "square_state",
    "association",
    "locale",
    "source",
    "model",
}
WRITES = {
    ("POST", "api/models"): "/api/models/",
    ("PUT", "api/models"): "/api/models/",
    ("POST", "api/models/delete"): "/api/models/delete",
    ("POST", "api/models/sync_upstream"): "/api/models/sync_upstream",
    ("POST", "api/vendors"): "/api/vendors/",
    ("PUT", "api/vendors"): "/api/vendors/",
    ("POST", "api/vendors/operations/preview"): "/api/vendors/operations/preview",
    ("POST", "api/vendors/operations"): "/api/vendors/operations",
    ("POST", "api/prefill_group"): "/api/prefill_group",
    ("PUT", "api/prefill_group"): "/api/prefill_group",
    ("PATCH", "api/option/model_pricing"): "/api/option/model_pricing",
    ("POST", "api/option/model_pricing/preview"): "/api/option/model_pricing/preview",
    ("POST", "api/option/model_pricing/convert"): "/api/option/model_pricing/convert",
    ("POST", "api/ratio_sync/fetch"): "/api/ratio_sync/fetch",
}
VENDOR_FIELDS = (
    "id",
    "name",
    "description",
    "icon",
    "status",
    "created_time",
    "updated_time",
    "model_count",
    "version",
)


def can_read(path: str) -> bool:
    return path in READS or bool(re.fullmatch(r"api/(models|vendors)/[1-9][0-9]*", path))


def query_params(request: Request) -> dict[str, str | int | list[str]]:
    pairs = request.query_params.multi_items()
    if len(pairs) > 1000 or any(len(value) > 2000 for _, value in pairs):
        raise HTTPException(422, "筛选条件超过大小上限")
    result: dict[str, str | int | list[str]] = {}
    for key, value in pairs:
        if key not in QUERY_FIELDS:
            continue
        if key in {"p", "page_size"}:
            if not value.isdecimal() or not 1 <= int(value) <= (
                1000 if key == "page_size" else 1000000
            ):
                raise HTTPException(422, "分页参数无效")
        if key == "model":
            names = result.setdefault(key, [])
            if isinstance(names, list):
                names.append(value)
        else:
            result[key] = value
    return result


def vendor_view(raw: Any) -> dict[str, Any]:
    row = service.object_value(raw)
    return {key: row.get(key) for key in VENDOR_FIELDS}


async def read(request: Request, db: DB, tenant_id: UUID, path: str) -> dict[str, Any]:
    if path == "api/pricing":
        # This public native contract puts groups/endpoints beside data.
        # Never proxy arbitrary option packets or management responses.
        response = await client.send(request, tenant_id, "GET", "/api/pricing")
        try:
            packet = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(502, "模型网关返回的数据格式不兼容") from exc
        if (
            not response.is_success
            or not isinstance(packet, dict)
            or packet.get("success") is not True
        ):
            raise HTTPException(502, "模型价格暂不可用")
        keys = (
            "data",
            "vendors",
            "group_ratio",
            "usable_group",
            "supported_endpoint",
            "auto_groups",
        )
        return {"success": True, **{key: packet.get(key) for key in keys}}
    target = READS.get(path, "/" + path)
    data = await client.call(request, tenant_id, "GET", target, params=query_params(request))
    if re.fullmatch(r"api/models/[1-9][0-9]*", path):
        data = service.model_view(data)
        await presentation.enrich(db, tenant_id, [data])
    elif re.fullmatch(r"api/vendors/[1-9][0-9]*", path):
        data = vendor_view(data)
    elif path in {"api/models", "api/models/search", "api/vendors", "api/vendors/search"}:
        page = service.object_value(data)
        convert = service.model_view if path.startswith("api/models") else vendor_view
        data = {key: page.get(key) for key in ("total", "page", "page_size", "vendor_counts")}
        data["items"] = [convert(row) for row in page.get("items", [])]
        if path.startswith("api/models"):
            await presentation.enrich(db, tenant_id, data["items"])
    elif path == "api/ratio_sync/channels":
        data = [
            {key: row.get(key) for key in ("id", "name", "type", "status", "base_url")}
            for row in data or []
        ]
    elif path == "api/option/model_pricing":
        for entry in data.get("entries", []):
            expression = entry.get("effective", {}).get("billing_setting.billing_expr")
            reference = pricing_reference(expression)
            if reference:
                entry["pricing_reference"] = reference
    return {"success": True, "data": data}


def resource_id(body: dict[str, JsonValue]) -> int:
    value = body.get("id")
    if type(value) is not int or value < 1:
        raise HTTPException(422, "资源 ID 无效")
    return value


async def mutate(
    request: Request, db: DB, actor: Access, path: str, body: dict[str, JsonValue] | None
) -> dict[str, Any]:
    method = request.method
    target = WRITES.get((method, path))
    deleting = re.fullmatch(r"api/(models|vendors|prefill_group)/([1-9][0-9]*)", path)
    if method == "DELETE" and deleting:
        target = "/" + path
    if not target:
        raise HTTPException(404, "此网关操作尚未接入")
    payload = dict(body) if body is not None else None
    if payload is not None and (len(payload) > 100 or len(json.dumps(payload)) > 2000000):
        raise HTTPException(422, "模型配置超过大小上限")
    params: dict[str, str | int] = {}
    display_name = None
    change = None
    if path == "api/models" and method in {"POST", "PUT"} and payload is not None:
        if "display_name" in payload:
            display_name = payload.pop("display_name")
            await db.scalar(select(Tenant.id).where(Tenant.id == actor.tenant.id).with_for_update())
            change = await presentation.prepare(request, db, actor.tenant.id, payload, display_name)
    if method == "PUT" and path == "api/models":
        if body is None:
            raise HTTPException(422, "缺少模型配置")
        model_id = resource_id(body)
        if request.query_params.get("status_only") == "true":
            if (
                set(body) != {"id", "status"}
                or type(body.get("status")) is not int
                or body["status"] not in (0, 1)
            ):
                raise HTTPException(422, "模型展示状态无效")
            params["status_only"] = "true"
        else:
            current = await client.call(request, actor.tenant.id, "GET", f"/api/models/{model_id}")
            view = service.model_view(current)
            await presentation.enrich(db, actor.tenant.id, [view])
            service.check_revision(view, request.headers.get("If-Match"))
    if method == "DELETE" and deleting and deleting[1] == "models":
        for key in ("remove_from_channels", "remove_pricing"):
            value = request.query_params.get(key, "false")
            if value not in {"true", "false"}:
                raise HTTPException(422, "模型删除选项无效")
            params[key] = value
    result = await client.call(
        request, actor.tenant.id, method, target, payload=payload, params=params
    )
    if change is not None and payload is not None:
        await presentation.save(db, actor.tenant.id, str(payload["model_name"]), change)
    if path == "api/models" and isinstance(result, dict) and result.get("model_name"):
        result = service.model_view(result)
        await presentation.enrich(db, actor.tenant.id, [result])
    elif path == "api/vendors" and isinstance(result, dict):
        result = vendor_view(result)
    # Native source/record/price versions stay intact. Audits contain only the
    # operation name, never metadata packets, expressions, secrets or headers.
    await audit(db, actor, "native." + method.lower(), path)
    return {"success": True, "data": result}
