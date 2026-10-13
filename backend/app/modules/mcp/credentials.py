import hashlib
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now, provider
from app.modules.mcp.models import McpConnection, McpHealth, McpService, McpSnapshot
from app.modules.mcp.oauth_tokens import token_request as token_request
from app.modules.members.service import BusinessActor

SHARED = UUID(int=0)


def owner(service: McpService, actor: BusinessActor) -> UUID:
    return actor.member.id if service.auth_mode in {"personal", "oauth"} else SHARED


def remember(request: Request, service_id: UUID, owner_id: UUID, sealed: str) -> None:
    stamps = getattr(request.state, "mcp_credentials", {})
    stamps[(service_id, owner_id)] = hashlib.sha256(sealed.encode()).hexdigest()
    request.state.mcp_credentials = stamps


def connection_guard(
    request: Request, db: AsyncSession, service: McpService, actor: BusinessActor
) -> Callable[[], Awaitable[None]]:
    key = (service.id, owner(service, actor))
    stamp = getattr(request.state, "mcp_credentials", {}).get(key)

    async def check() -> None:
        if service.auth_mode == "none":
            return
        # Scalar reads cannot reuse a stale ORM connection after disconnect/replacement.
        sealed = await db.scalar(
            select(McpConnection.sealed).where(
                McpConnection.service_id == key[0], McpConnection.owner_id == key[1]
            )
        )
        if not sealed or stamp != hashlib.sha256(sealed.encode()).hexdigest():
            raise HTTPException(409, "连接已断开或凭据已替换，请重新验证；不会自动重试")

    return check


async def store(
    request: Request,
    db: AsyncSession,
    service: McpService,
    actor: BusinessActor,
    values: dict[str, Any],
) -> None:
    key = (service.id, owner(service, actor))
    row = await db.scalar(
        select(McpConnection)
        .where(McpConnection.service_id == key[0], McpConnection.owner_id == key[1])
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    sealed = provider(request).seal(values)
    if row:
        row.sealed = sealed
        row.updated_at = now()
    else:
        db.add(McpConnection(service_id=key[0], owner_id=key[1], sealed=sealed))
    await db.execute(
        delete(McpHealth).where(McpHealth.service_id == key[0], McpHealth.owner_id == key[1])
    )
    await db.execute(
        delete(McpSnapshot).where(McpSnapshot.service_id == key[0], McpSnapshot.owner_id == key[1])
    )


async def headers_for(
    request: Request, db: AsyncSession, service: McpService, actor: BusinessActor
) -> tuple[dict[str, str], list[str]]:
    return await headers_for_owner(request, db, service, owner(service, actor))


async def headers_for_owner(
    request: Request, db: AsyncSession, service: McpService, owner_id: UUID
) -> tuple[dict[str, str], list[str]]:
    if service.auth_mode == "none":
        return {}, []
    if service.auth_mode == "oauth":
        from app.modules.mcp.oauth_refresh import values as oauth_values

        values = await oauth_values(request, service, owner_id)
        return {"Authorization": "Bearer " + values["access_token"]}, [
            str(v) for v in values.values() if isinstance(v, str)
        ]
    row = await db.get(McpConnection, (service.id, owner_id), populate_existing=True)
    if row is None:
        raise HTTPException(
            409,
            "请先配置当前账号的凭据"
            if service.auth_mode != "organization"
            else "管理员尚未配置组织凭据",
        )
    values = provider(request).unseal(row.sealed)
    remember(request, service.id, owner_id, row.sealed)
    headers = {}
    for field in service.credential_fields:
        value = values.get(field["key"])
        if not isinstance(value, str) or not value:
            raise HTTPException(409, "凭据字段已变化，请重新配置")
        headers[field["header"]] = ("Bearer " if field["bearer"] else "") + value
    return headers, list(values.values())
