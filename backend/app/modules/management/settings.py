"""Deployment default with an explicit, persisted platform choice."""

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import provider
from app.modules.desktop.errors import fail
from app.modules.tenants.models import Installation


async def require_enabled(request: Request, db: AsyncSession) -> None:
    # Select the scalar on every authorization boundary, avoiding identity-map caches.
    override = await db.scalar(select(Installation.management_enabled).where(Installation.id == 1))
    enabled = provider(request).settings.management_enabled if override is None else override
    if not enabled:
        fail(503, "management_disabled", "此平台尚未开启 CLI 管理接口")
