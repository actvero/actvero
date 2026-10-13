import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException, Request
from jsonschema import Draft202012Validator
from referencing import Registry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now, provider
from app.modules.mcp.activity import add_activity
from app.modules.mcp.credentials import connection_guard, headers_for, owner
from app.modules.mcp.models import (
    McpConnection,
    McpContent,
    McpHealth,
    McpPolicy,
    McpService,
    McpSnapshot,
)
from app.modules.mcp.runtime import call_tool, connect, discover
from app.modules.mcp.schemas import (
    McpCapabilities,
    McpCapability,
    McpResult,
    McpRun,
    McpServiceView,
)
from app.modules.members.service import Access, BusinessActor, record

DispatchGuard = Callable[[dict[str, Any] | None], Awaitable[None]]


def definition_hash(definition: dict[str, Any]) -> str:
    contract = {
        k: definition.get(k)
        for k in ("inputSchema", "outputSchema", "arguments", "uriTemplate", "uri", "mimeType")
    }
    return hashlib.sha256(json.dumps(contract, sort_keys=True).encode()).hexdigest()


def capability_allowed(rule: McpPolicy | None, capability: dict[str, Any]) -> bool:
    return bool(
        rule and rule.enabled and rule.definition_hash == definition_hash(capability["definition"])
    )


def can_test(actor: BusinessActor) -> bool:
    return isinstance(actor, Access) and actor.member.role == "administrator"


def administrator(actor: BusinessActor) -> None:
    if not can_test(actor):
        raise HTTPException(403, "此操作仅限管理员")


def visible(service: McpService, actor: BusinessActor) -> bool:
    return service.enabled and (
        service.audience == "organization" or str(actor.member.id) in service.member_ids
    )


async def get_service(
    db: AsyncSession, actor: BusinessActor, service_id: UUID, admin: bool = False
) -> McpService:
    row = await db.get(McpService, service_id)
    if row is None or row.tenant_id != actor.tenant.id:
        raise HTTPException(404, "MCP 服务不存在")
    if admin:
        administrator(actor)
    elif not can_test(actor) and not visible(row, actor):
        raise HTTPException(404, "MCP 服务不可用")
    return row


async def contents(
    db: AsyncSession, service: McpService, enabled_only: bool = False
) -> list[McpContent]:
    query = select(McpContent).where(McpContent.service_id == service.id)
    if enabled_only:
        query = query.where(McpContent.enabled.is_(True))
    return list((await db.scalars(query)).all())


async def policies(db: AsyncSession, service: McpService) -> dict[tuple[str, str], McpPolicy]:
    return {
        (r.kind, r.key): r
        for r in (
            await db.scalars(
                select(McpPolicy)
                .where(McpPolicy.service_id == service.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    }


def redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        for secret in sorted((s for s in secrets if s), key=len, reverse=True):
            value = value.replace(secret, "[已隐藏凭据]")
        return value
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, dict):
        return {str(redact(k, secrets)): redact(v, secrets) for k, v in value.items()}
    return value


async def view(db: AsyncSession, service: McpService, actor: BusinessActor) -> McpServiceView:
    snapshot = await db.get(McpSnapshot, (service.id, owner(service, actor)))
    rules = await policies(db, service)
    entries = snapshot.capabilities if snapshot else []
    if not can_test(actor):
        entries = [
            c
            for c in entries
            if (rule := rules.get((c["kind"], c["key"]))) and capability_allowed(rule, c)
        ]
    health = await db.get(McpHealth, (service.id, owner(service, actor)))
    return McpServiceView(
        connection_options=service.connection_options or {},
        health_checked_at=health.checked_at if health else None,
        health_error=health.error if health else None,
        id=service.id,
        version=service.version,
        name=service.name,
        description=service.description,
        display_name=service.display_name,
        icon=service.icon,
        examples=service.examples,
        transport=service.transport,
        url=service.url,
        enabled=service.enabled,
        audience=service.audience,
        member_ids=service.member_ids if actor.member.role == "administrator" else [],
        auth_mode=service.auth_mode,
        credential_fields=service.credential_fields,
        oauth=service.oauth,
        configured=service.auth_mode == "none"
        or await db.get(McpConnection, (service.id, owner(service, actor))) is not None,
        checked_at=snapshot.checked_at if snapshot else None,
        error=snapshot.error if snapshot else None,
        protocol=snapshot.protocol if snapshot else "",
        counts={
            k: sum(c["kind"] == k for c in entries)
            for k in ("tools", "prompts", "resources", "templates")
        },
    )


async def capability_view(
    db: AsyncSession, service: McpService, actor: BusinessActor
) -> McpCapabilities:
    snapshot = await db.get(McpSnapshot, (service.id, owner(service, actor)))
    rules = await policies(db, service)
    items = []
    for c in snapshot.capabilities if snapshot else []:
        rule = rules.get((c["kind"], c["key"]))
        if not can_test(actor) and not capability_allowed(rule, c):
            continue
        items.append(
            McpCapability(
                **{
                    **c,
                    "description": rule.description
                    if rule and rule.description is not None
                    else c["description"],
                },
                original_description=c["description"],
                enabled=capability_allowed(rule, c),
            )
        )
    return McpCapabilities(
        items=items,
        protocol=snapshot.protocol if snapshot else "",
        negotiated=snapshot.negotiated if snapshot else {},
        checked_at=snapshot.checked_at if snapshot else None,
        error=snapshot.error if snapshot else None,
    )


async def _refresh(
    request: Request,
    db: AsyncSession,
    service: McpService,
    actor: BusinessActor,
    guard: DispatchGuard | None = None,
) -> McpCapabilities:
    headers, secrets = await headers_for(request, db, service, actor)
    check_connection = connection_guard(request, db, service, actor)
    await check_connection()
    if guard:
        await guard(None)
    snapshot = await db.get(McpSnapshot, (service.id, owner(service, actor)))
    if not snapshot:
        snapshot = McpSnapshot(
            service_id=service.id, owner_id=owner(service, actor), capabilities=[]
        )
        db.add(snapshot)
    try:
        async with connect(
            service, provider(request).settings, headers, await contents(db, service)
        ) as client:
            data = await discover(client)
            protocol = client.protocol_version or ""
            negotiated = (
                client.server_capabilities.model_dump(mode="json", by_alias=True)
                if client.server_capabilities
                else {}
            )
    except Exception:
        # Never persist transport errors: they can include credentials and upstream URLs.
        snapshot.error = "连接失败，请检查地址、凭据与服务状态；保留上次成功的目录"
        record(db, actor, "mcp.discover", service.id, service.name, result="failed")
        await db.commit()
        raise HTTPException(502, snapshot.error) from None
    await check_connection()
    if guard:
        await guard(None)
    snapshot.capabilities = redact(data, secrets)
    snapshot.protocol = protocol
    snapshot.negotiated = negotiated
    snapshot.checked_at = now()
    snapshot.error = None
    rules = await policies(db, service)
    first_admin_discovery = not service.catalog_initialized and can_test(actor)
    builtin_content = await contents(db, service) if service.transport == "builtin" else []
    for c in data:
        key = (c["kind"], c["key"])
        if key not in rules and isinstance(actor, Access):
            enabled = (first_admin_discovery and service.transport != "builtin") or any(
                i.enabled
                and (
                    i.name == c["key"]
                    if i.kind == "prompts"
                    else f"actvero://resources/{i.id}" == c["key"]
                )
                for i in builtin_content
            )
            db.add(
                McpPolicy(
                    service_id=service.id,
                    kind=key[0],
                    key=key[1],
                    enabled=enabled,
                    definition_hash=definition_hash(c["definition"]),
                )
            )
    if can_test(actor):
        service.catalog_initialized = True
    record(db, actor, "mcp.discover", service.id, service.name)
    await db.flush()
    return await capability_view(db, service, actor)


async def _run(
    request: Request,
    db: AsyncSession,
    service: McpService,
    actor: BusinessActor,
    body: McpRun,
    guard: DispatchGuard | None = None,
) -> McpResult:
    admin = can_test(actor)
    if not admin and not visible(service, actor):
        raise HTTPException(403, "服务未开放")
    rule = await db.get(McpPolicy, (service.id, body.kind, body.key))
    if not admin and (rule is None or not rule.enabled):
        raise HTTPException(403, "该能力未开放")
    if len(json.dumps(body.arguments)) > 100000:
        raise HTTPException(422, "输入参数过大")
    headers, secrets = await headers_for(request, db, service, actor)
    check_connection = connection_guard(request, db, service, actor)
    await check_connection()
    if guard:
        await guard(None)
    started = time.monotonic()
    try:
        async with connect(
            service,
            provider(request).settings,
            headers,
            await contents(db, service, enabled_only=not admin),
        ) as client:
            # Never trust a previous principal's catalog or a client-provided tool/schema/URI.
            directory = await discover(client)
            entry = next(
                (c for c in directory if c["kind"] == body.kind and c["key"] == body.key), None
            )
            if entry is None:
                raise HTTPException(409, "此能力当前不可用，请刷新目录")
            if not admin and not capability_allowed(rule, entry):
                raise HTTPException(409, "能力定义已变化，请管理员重新确认启用")
            from app.modules.access_keys import service as keys

            if isinstance(actor, keys.KeyActor):
                await keys.authorize(
                    request, db, "mcp", service.id, "invoke" if body.kind == "tools" else "read"
                )
                current = await db.get(McpService, service.id, populate_existing=True)
                if not current or not visible(current, actor):
                    raise HTTPException(403, "服务未开放")
                await db.refresh(rule)
                if not capability_allowed(rule, entry):
                    raise HTTPException(403, "该能力未开放")
            await check_connection()
            if guard:
                await guard({**entry, "_protocol": client.protocol_version or ""})
            definition = entry["definition"]
            if body.kind == "tools":
                try:
                    Draft202012Validator(
                        definition.get("inputSchema", {}), registry=Registry()
                    ).validate(body.arguments)
                except Exception as exc:
                    raise HTTPException(
                        422, "参数不符合工具定义；外部 Schema 引用不受支持"
                    ) from exc
                result = (await call_tool(client, service, body.key, body.arguments)).model_dump(
                    mode="json", by_alias=True
                )
            elif body.kind == "prompts":
                required = {a["name"] for a in definition.get("arguments", []) if a.get("required")}
                allowed = {a["name"] for a in definition.get("arguments", [])}
                if (
                    not required.issubset(body.arguments)
                    or set(body.arguments) - allowed
                    or any(not isinstance(v, str) for v in body.arguments.values())
                ):
                    raise HTTPException(422, "请按提示词定义填写文本参数")
                result = (await client.get_prompt(body.key, body.arguments)).model_dump(
                    mode="json", by_alias=True
                )
            else:
                uri = body.key
                if body.kind == "templates":
                    # SDK's RFC6570 matcher validates expansion without fetching arbitrary URIs.
                    from fastmcp.resources.template import match_uri_template

                    if not body.uri or match_uri_template(body.uri, body.key) is None:
                        raise HTTPException(422, "资源地址不符合模板")
                    uri = body.uri
                result = {
                    "contents": [
                        c.model_dump(mode="json", by_alias=True)
                        for c in await client.read_resource(uri)
                    ]
                }
            await check_connection()
            if guard:
                await guard({**entry, "_protocol": client.protocol_version or ""})
            if len(json.dumps(result)) > 2_000_000:
                raise HTTPException(502, "结果超过 2 MB 预览限制")
    except TimeoutError:
        record(db, actor, "mcp.run", service.id, service.name, {"kind": body.kind}, result="failed")
        await db.commit()
        raise HTTPException(504, "上游响应超时；不会自动重试") from None
    except HTTPException:
        record(db, actor, "mcp.run", service.id, service.name, {"kind": body.kind}, result="failed")
        await db.commit()
        raise
    except Exception:
        record(db, actor, "mcp.run", service.id, service.name, {"kind": body.kind}, result="failed")
        await db.commit()
        raise HTTPException(502, "执行未确认完成，请检查上游状态；不会自动重试") from None
    record(
        db,
        actor,
        "mcp.run",
        service.id,
        service.name,
        {"kind": body.kind},
        result="failed" if result.get("isError") else "success",
    )
    return McpResult(
        result=cast(dict[str, Any], redact(result, secrets)),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


async def refresh(
    request: Request,
    db: AsyncSession,
    service: McpService,
    actor: BusinessActor,
    guard: DispatchGuard | None = None,
) -> McpCapabilities:
    started = time.monotonic()
    try:
        result = await _refresh(request, db, service, actor, guard)
    except Exception as exc:
        add_activity(db, request, service, actor, "connection", "discover", started, error=exc)
        await db.commit()
        raise
    add_activity(db, request, service, actor, "connection", "discover", started)
    return result


async def run(
    request: Request,
    db: AsyncSession,
    service: McpService,
    actor: BusinessActor,
    body: McpRun,
    guard: DispatchGuard | None = None,
) -> McpResult:
    started = time.monotonic()
    # Resource URIs may contain business data. Record a known catalog name, never arbitrary input.
    snapshot = await db.get(McpSnapshot, (service.id, owner(service, actor)))
    name = (
        next(
            (
                c["name"]
                for c in snapshot.capabilities
                if c["kind"] == body.kind and c["key"] == body.key
            ),
            "",
        )
        if snapshot
        else ""
    )
    try:
        result = await _run(request, db, service, actor, body, guard)
    except Exception as exc:
        add_activity(db, request, service, actor, "call", body.kind, started, name, error=exc)
        await db.commit()
        raise
    add_activity(
        db,
        request,
        service,
        actor,
        "call",
        body.kind,
        started,
        name,
        tool_error=bool(result.result.get("isError")),
    )
    return result
