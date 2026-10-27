"""Bounded, authenticated New API calls with no cross-organization credentials."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import httpx2
from fastapi import HTTPException, Request
from pydantic import SecretStr

from app.core.outbound import PinnedTransport, resolve
from app.modules.auth.service import provider
from app.modules.model_gateway.config import NewApiConnection


def connection(request: Request, tenant_id: UUID) -> NewApiConnection | None:
    settings = provider(request).settings
    gateway = settings.newapi_gateway
    if gateway:
        cached = getattr(request.state, "newapi_organization", {})
        return cached.get(tenant_id) or NewApiConnection(
            tenant_id=tenant_id,
            namespace="avt_" + tenant_id.hex + "__",
            base_url=gateway.base_url,
            management_token=gateway.management_token,
        )
    return next(
        (c for c in provider(request).settings.newapi_connections if c.tenant_id == tenant_id), None
    )


def require_connection(request: Request, tenant_id: UUID) -> NewApiConnection:
    result = connection(request, tenant_id)
    if result is None:
        raise HTTPException(409, "本组织尚未连接模型网关")
    return result


def connection_id(config: NewApiConnection) -> str:
    return hashlib.sha256(
        (
            config.base_url
            + "\0"
            + config.management_token.get_secret_value()
            + "\0"
            + (config.namespace or "")
        ).encode()
    ).hexdigest()


def revision(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


async def send(
    request: Request,
    tenant_id: UUID,
    method: str,
    path: str,
    *,
    payload: Any = None,
    params: Mapping[str, str | int | Sequence[str]] | None = None,
) -> httpx2.Response:
    config = await relay_connection(request, tenant_id)
    if config.namespace:
        return await _send(
            request,
            config,
            "POST",
            f"/api/actvero/organizations/{tenant_id}/bridge",
            payload={
                "method": method,
                "path": path,
                "params": dict(params or {}),
                "payload": payload,
            },
        )
    verified: set[str] = getattr(request.state, "newapi_legacy_verified", set())
    identity = connection_id(config)
    if identity not in verified:
        probe = await _send(request, config, "GET", "/api/status")
        try:
            packet = probe.json()
            if (
                not probe.is_success
                or packet.get("success") is not True
                or not isinstance(packet.get("data"), dict)
            ):
                raise ValueError
            isolated = packet["data"].get("actvero_organization_isolation")
        except (ValueError, AttributeError) as exc:
            raise HTTPException(502, "无法核对网关连接模式，未发起操作") from exc
        if isolated is True:
            raise HTTPException(409, "此网关已启用组织隔离，请使用部署级网关连接配置")
        verified.add(identity)
        request.state.newapi_legacy_verified = verified
        if method == "GET" and path.rstrip("/") == "/api/status":
            return probe
    return await _send(request, config, method, path, payload=payload, params=params)


async def relay_connection(request: Request, tenant_id: UUID) -> NewApiConnection:
    config = require_connection(request, tenant_id)
    if not config.namespace or config.relay_key:
        return config
    response = await _send(
        request, config, "POST", f"/api/actvero/organizations/{tenant_id}/connect"
    )
    try:
        packet = response.json()
        data = packet["data"]
        if not response.is_success or packet.get("success") is not True:
            raise ValueError
        if (
            data["schema_version"] != 1
            or data["namespace"] != config.namespace
            or data["relay_group"] != "default"
            or type(data["relay_token_id"]) is not int
            or data["relay_token_id"] < 1
            or not isinstance(data["relay_key"], str)
            or not 32 <= len(data["relay_key"]) <= 100
        ):
            raise ValueError
        config = config.model_copy(
            update={
                "relay_key": SecretStr(data["relay_key"]),
                "relay_token_id": data["relay_token_id"],
                "relay_group": "default",
            }
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, "无法建立组织网关连接，请检查网关版本及服务凭据") from exc
    cached = getattr(request.state, "newapi_organization", {})
    cached[tenant_id] = config
    request.state.newapi_organization = cached
    return config


async def _send(
    request: Request,
    config: NewApiConnection,
    method: str,
    path: str,
    *,
    payload: Any = None,
    params: Mapping[str, str | int | Sequence[str]] | None = None,
) -> httpx2.Response:
    settings = provider(request).settings
    url = config.base_url + path

    async def resolver(target: str) -> str:
        return await resolve(
            target, settings.llm_allowed_private_origins, dns=settings.llm_public_dns
        )

    transport = PinnedTransport(config.base_url, resolver, max_bytes=4_000_000)
    # Never propagate browser cookies, a supplied URL, ambient proxy settings,
    # management credentials in an error, or automatic retries of writes.
    try:
        async with httpx2.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False, timeout=45
        ) as client:
            response = await client.request(
                method,
                url,
                params=params,
                json=payload,
                headers={
                    "Authorization": "Bearer " + config.management_token.get_secret_value(),
                    "Accept-Language": "zh-CN",
                },
            )
    except (httpx2.HTTPError, TimeoutError) as exc:
        message = (
            "模型网关暂不可用，请稍后重试"
            if method == "GET"
            else "未能确认网关操作结果，请刷新查看后再操作"
        )
        raise HTTPException(502, message) from exc
    return response


async def call(
    request: Request,
    tenant_id: UUID,
    method: str,
    path: str,
    *,
    payload: Any = None,
    params: Mapping[str, str | int | Sequence[str]] | None = None,
) -> Any:
    response = await send(request, tenant_id, method, path, payload=payload, params=params)
    try:
        data = response.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(502, "模型网关返回了无法识别的响应") from exc
    if response.status_code in {401, 403}:
        raise HTTPException(502, "模型网关管理凭据无效或权限不足，请检查部署配置")
    if response.status_code == 404 and require_connection(request, tenant_id).namespace:
        raise HTTPException(404, "组织网关资源或操作不存在")
    if response.status_code == 409:
        raise HTTPException(409, "网关配置已变更，请刷新后重试")
    if response.status_code == 429:
        raise HTTPException(429, "模型网关请求过于频繁，请稍后重试")
    if not response.is_success or not isinstance(data, dict) or data.get("success") is not True:
        # The upstream can include credentials, arbitrary request bodies, or
        # provider errors. Keep those out of the platform response and audit.
        raise HTTPException(502, "模型网关未接受此次操作，请检查配置；保存操作请先刷新核对结果")
    if path.startswith("/api/channel/test/"):
        return {"time": data.get("time")}
    return data.get("data")
