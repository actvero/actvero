"""Serialize each owner's rotation; commit independently of the later MCP operation."""

import asyncio
import math
import time
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.modules.auth.service import now, provider
from app.modules.mcp.models import McpConnection, McpService
from app.modules.mcp.oauth_tokens import AuthorizationExpired, RefreshUnavailable
from app.modules.members.models import Membership
from app.modules.tenants.models import Tenant

_pending: set[asyncio.Task[dict[str, Any]]] = set()
STATE = "_mcp_refresh"


def retry_state(values: dict[str, Any]) -> tuple[bool, int]:
    state = values.get(STATE, {})
    if not isinstance(state, dict):
        return False, 0
    try:
        retry_at = float(state.get("retry_at", 0))
        retry = max(0, math.ceil(retry_at - time.time())) if math.isfinite(retry_at) else 0
    except (ValueError, TypeError, OverflowError):
        retry = 0
    return bool(state.get("reauthorization_required")), retry


async def _rotate(request: Request, original: McpService, owner_id: UUID) -> dict[str, Any]:
    from app.modules.mcp import credentials

    failure: HTTPException | None = None
    values: dict[str, Any] = {}
    async with request.app.state.database.sessions() as db:
        try:
            # Callers may hold the organization lock; never take it again here.
            await db.execute(text("SET LOCAL lock_timeout = '5s'"))
            row = await db.scalar(
                select(McpConnection)
                .where(McpConnection.service_id == original.id, McpConnection.owner_id == owner_id)
                .with_for_update()
            )
            current = await db.get(McpService, original.id)
            member = await db.get(Membership, owner_id)
            tenant = await db.get(Tenant, original.tenant_id)
            if (
                not member
                or member.tenant_id != original.tenant_id
                or member.status != "active"
                or not tenant
                or not tenant.active
            ):
                raise HTTPException(403, "当前账号无有效连接权限")
            if (
                not current
                or current.tenant_id != original.tenant_id
                or current.version != original.version
                or current.auth_mode != "oauth"
                or current.oauth != original.oauth
            ):
                raise HTTPException(409, "连接器配置已变化，请重新读取后重试")
            if member.role != "administrator" and (
                not current.enabled
                or current.audience != "organization"
                and str(owner_id) not in current.member_ids
            ):
                raise HTTPException(403, "当前账号无有效连接权限")
            if not row:
                raise HTTPException(409, "请先授权当前账号")
            values = provider(request).unseal(row.sealed)
            expired, retry = retry_state(values)
            if expired:
                raise AuthorizationExpired()
            if retry:
                raise RefreshUnavailable(retry)
            if values.get("expires_at", 0) <= time.time() + 30:
                if not values.get("refresh_token") or not current.oauth:
                    failure = AuthorizationExpired()
                    values[STATE] = {"reauthorization_required": True}
                else:
                    try:
                        refreshed = await credentials.token_request(
                            request,
                            current.oauth["token_url"],
                            {
                                "grant_type": "refresh_token",
                                "refresh_token": values["refresh_token"],
                                "client_id": current.oauth["client_id"],
                            },
                        )
                        values = {**values, **refreshed}
                        values.pop(STATE, None)
                    except AuthorizationExpired as exc:
                        failure = exc
                        values[STATE] = {"reauthorization_required": True}
                    except HTTPException as exc:
                        failure = exc
                        wait = exc.seconds if isinstance(exc, RefreshUnavailable) else 30
                        values[STATE] = {"retry_at": time.time() + wait}
                    row.sealed = provider(request).seal(values)
                    row.updated_at = now()
                if failure and isinstance(failure, AuthorizationExpired):
                    row.sealed = provider(request).seal(values)
                    row.updated_at = now()
            await db.commit()
            if not failure:
                credentials.remember(request, current.id, owner_id, row.sealed)
        except DBAPIError:
            await db.rollback()
            raise RefreshUnavailable() from None
    if failure:
        raise failure
    return values


async def values(request: Request, service: McpService, owner_id: UUID) -> dict[str, Any]:
    task = asyncio.create_task(_rotate(request, service, owner_id))
    _pending.add(task)

    def finished(done: asyncio.Task[dict[str, Any]]) -> None:
        _pending.discard(done)
        if not done.cancelled():
            done.exception()  # Consume a failure when the waiting HTTP request was cancelled.

    task.add_done_callback(finished)
    # A cancelled MCP request cannot roll back a known upstream rotation. This performs
    # only token refresh/persistence, never a background business tool call.
    return cast(dict[str, Any], await asyncio.shield(task))
