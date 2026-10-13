"""Database-coordinated probes; no business calls or capability-policy changes."""

import asyncio
import logging
import time
from contextlib import suppress
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.modules.auth.service import now
from app.modules.mcp.activity import failure
from app.modules.mcp.credentials import SHARED, headers_for_owner
from app.modules.mcp.models import McpActivity, McpConnection, McpHealth, McpService
from app.modules.mcp.runtime import connect
from app.modules.mcp.schemas import ConnectionOptions
from app.modules.members.models import Membership
from app.modules.tenants.models import Installation, Tenant
from app.modules.users.models import User

logger = logging.getLogger(__name__)


async def probe(app: FastAPI, service_id: UUID, owner_id: UUID) -> bool:
    async with app.state.database.sessions() as db:
        row = await db.get(McpService, service_id)
        if row is None:
            return False
        # Same tenant lock as membership/config writes; a revoked principal cannot be probed.
        tenant = await db.scalar(
            select(Tenant).where(Tenant.id == row.tenant_id).with_for_update(skip_locked=True)
        )
        platform_edition = app.state.identity_provider.settings.platform_edition
        installation = await db.get(Installation, 1) if platform_edition == "community" else None
        if (
            not tenant
            or not tenant.active
            or (
                platform_edition == "community"
                and (not installation or installation.tenant_id != tenant.id)
            )
        ):
            return False
        await db.refresh(row)
        options = ConnectionOptions.model_validate(row.connection_options or {})
        if not row.enabled or not options.health_enabled or row.transport == "builtin":
            return False
        actor_id, actor_name = None, "系统"
        if row.auth_mode in ("personal", "oauth"):
            member = await db.get(Membership, owner_id)
            if not member or member.tenant_id != tenant.id or member.status != "active":
                return False
            if (
                member.role != "administrator"
                and row.audience != "organization"
                and str(member.id) not in row.member_ids
            ):
                return False
            user = await db.get(User, member.user_id)
            if user is None:
                return False
            actor_id, actor_name = user.id, user.name
        elif owner_id != SHARED:
            return False
        if row.auth_mode != "none" and not await db.get(McpConnection, (row.id, owner_id)):
            return False
        await db.execute(
            insert(McpHealth)
            .values(service_id=row.id, owner_id=owner_id, next_check_at=now(), failures=0)
            .on_conflict_do_nothing()
        )
        health = await db.get(McpHealth, (row.id, owner_id))
        assert health is not None
        if health.next_check_at > now():
            return False
        request = Request({"type": "http", "app": app})
        started = time.monotonic()
        previous_error = health.error
        error: Exception | None = None
        try:
            # Bound each probe separately from potentially long-running tool calls.
            async with asyncio.timeout(min(options.total_timeout, 30)):
                headers, _ = await headers_for_owner(request, db, row, owner_id)
                async with connect(
                    row, app.state.identity_provider.settings, headers, []
                ) as client:
                    await client.ping()
        except Exception as exc:
            error = exc
        result, code, message = failure(error) if error else ("success", "", "")
        health.checked_at = now()
        health.error = message or None
        health.failures = health.failures + 1 if error else 0
        health.next_check_at = now() + timedelta(
            seconds=min(options.health_interval * 2 ** min(health.failures, 4), 3600)
        )
        db.add(
            McpActivity(
                tenant_id=tenant.id,
                service_id=row.id,
                service_name=row.name,
                actor_id=actor_id,
                actor_name=actor_name,
                owner_id=owner_id,
                category="connection",
                operation="recovered" if previous_error and not error else "health_check",
                source="health",
                result=result,
                duration_ms=int((time.monotonic() - started) * 1000),
                error_code=code,
                message=message,
                request_id=uuid4().hex,
            )
        )
        await db.commit()
        return True


async def check_once(app: FastAPI) -> None:
    async with app.state.database.sessions() as db:
        rows = (await db.scalars(select(McpService).where(McpService.enabled.is_(True)))).all()
        targets: list[tuple[UUID, UUID]] = []
        for row in rows:
            if (
                not (row.connection_options or {}).get("health_enabled")
                or row.transport == "builtin"
            ):
                continue
            if row.auth_mode in ("personal", "oauth"):
                owners = (
                    await db.scalars(
                        select(McpConnection.owner_id).where(McpConnection.service_id == row.id)
                    )
                ).all()
            else:
                owners = [SHARED]
            targets.extend((row.id, owner_id) for owner_id in owners)
    for service_id, owner_id in targets:
        await probe(app, service_id, owner_id)


async def monitor(app: FastAPI) -> None:
    while True:
        # Delay the first scan until startup/migrations have completed.
        await asyncio.sleep(5)
        try:
            await check_once(app)
        except Exception:
            # Do not print exception text: a transport may embed upstream credentials.
            logger.warning("MCP health scan failed; next scan will retry")


async def stop(task: asyncio.Task[None] | None) -> None:
    if task:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
