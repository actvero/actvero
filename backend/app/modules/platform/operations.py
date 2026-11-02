"""Shared platform Web/CLI authentication and installation mutation lock."""

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import mutation_session
from app.modules.management.service import actor as management_actor
from app.modules.platform.access import PlatformActor, require_system_grant, system_access
from app.modules.tenants.models import Installation


async def access(
    request: Request, db: AsyncSession, permission: str | None = None
) -> PlatformActor:
    if request.url.path.startswith("/api/v1/management/"):
        who = await management_actor(request, db)
        if who.session.scope != "platform:read":
            raise HTTPException(403, "请使用平台发布管理登录，组织凭据不能用于此接口")
        if permission and permission not in who.session.platform_permissions:
            raise HTTPException(403, "CLI 会话未获得此平台操作权限，请重新登录授权")
        return PlatformActor(who.user)
    if permission:
        await mutation_session(request, db)
    return await system_access(request, db)


async def locked(request: Request, db: AsyncSession, permission: str) -> PlatformActor:
    who = await access(request, db, permission)
    if not await db.scalar(select(Installation).where(Installation.id == 1).with_for_update()):
        raise HTTPException(503, "数据库尚未完成迁移")
    if request.url.path.startswith("/api/v1/management/"):
        return await access(request, db, permission)
    await require_system_grant(request, db, who)
    return who


class RevisionConflict(HTTPException):
    code = "revision_conflict"

    def __init__(self) -> None:
        super().__init__(409, "记录已改变，请读取最新记录后核对")


def revision(actual: int, expected: int) -> None:
    if actual != expected:
        raise RevisionConflict()
