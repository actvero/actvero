"""Revalidate CLI authority at every network dispatch boundary without holding login locks."""

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.desktop.errors import fail
from app.modules.management import service
from app.modules.mcp import service as mcp
from app.modules.mcp.models import McpService
from app.modules.mcp.schemas import McpCapabilities, McpResult, McpRun
from app.modules.mcp.service import DispatchGuard
from app.modules.members.service import ManagementBusinessActor


async def guard_for(
    request: Request, db: AsyncSession, actor: ManagementBusinessActor, service_id: UUID
) -> tuple[McpService, DispatchGuard]:
    row = await mcp.get_service(db, actor, service_id)
    version, org_id = row.version, actor.tenant.id
    await db.commit()

    async def guard(_entry: dict[str, Any] | None) -> None:
        async with request.app.state.database.sessions() as current_db:
            who = await service.actor(request, current_db)
            current_actor, _ = await service.organization(
                request, current_db, who, org_id, require_admin=True, write=True
            )
            current = await mcp.get_service(current_db, current_actor, service_id)
            if current.version != version:
                fail(409, "connector_changed", "连接器配置已变化，请重新读取")
            await current_db.commit()

    return row, guard


async def run(
    actor: ManagementBusinessActor,
    service_id: UUID,
    request: Request,
    db: AsyncSession,
    body: McpRun,
) -> McpResult:
    row, guard = await guard_for(request, db, actor, service_id)
    return await mcp.run(request, db, row, actor, body, guard)


async def discover(
    actor: ManagementBusinessActor, service_id: UUID, request: Request, db: AsyncSession
) -> McpCapabilities:
    row, guard = await guard_for(request, db, actor, service_id)
    return await mcp.refresh(request, db, row, actor, guard)
