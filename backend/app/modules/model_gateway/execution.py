"""Bind a single native gateway hop; supplier selection/retries belong to New API."""

from uuid import UUID

from fastapi import HTTPException, Request

from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.providers.sdk_router import Candidate
from app.modules.model_gateway import client
from app.modules.model_gateway.publication import origin_hash


async def prepare(
    request: Request, tenant_id: UUID, config: CatalogInput, pool: list[Candidate]
) -> None:
    if config.gateway is None:
        return
    connection = await client.relay_connection(request, tenant_id)
    if (
        origin_hash(connection.base_url) != config.gateway.origin_hash
        or not connection.relay_key
        or not connection.relay_token_id
    ):
        raise HTTPException(409, "网关调用连接已变化，请重新保存模型的成员访问配置")
    if len(pool) != 1 or config.routing.fallback or config.routing.mode != "fixed":
        raise HTTPException(409, "网关模型只能使用单次网关调用")
    status = await client.call(request, tenant_id, "GET", "/api/status")
    unit = status.get("quota_per_unit")
    if type(unit) not in (int, float) or not 0 < unit <= 10**12:
        raise HTTPException(502, "网关未返回有效的计费单位")
    candidate = pool[0]
    if candidate.base != connection.base_url + "/v1" and config.kind != "rerank":
        raise HTTPException(409, "网关连接地址不一致，请重新保存成员访问配置")
    if connection.namespace:
        candidate.model = connection.namespace + candidate.model
        candidate.evidence["upstream_id"] = candidate.model
        if "model" in candidate.payload:
            candidate.payload["model"] = candidate.model
    candidate.key = connection.relay_key.get_secret_value()
    candidate.protect = False
    candidate.evidence["gateway"] = {
        "origin_hash": config.gateway.origin_hash,
        "token_id": connection.relay_token_id,
        "quota_per_unit": unit,
    }
