from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy import select

from app.modules.auth.service import DB, authenticate, provider
from app.modules.tenants.models import PlatformOperator
from app.modules.users.models import User


@dataclass
class PlatformActor:
    user: User


async def platform_access(request: Request, db: DB) -> PlatformActor:
    if provider(request).settings.platform_edition != "saas":
        raise HTTPException(404, "社区版不提供平台组织管理")
    _, _, user = await authenticate(request, db)
    operator = await db.scalar(
        select(PlatformOperator).where(
            PlatformOperator.user_id == user.id, PlatformOperator.status == "active"
        )
    )
    if operator is None:
        raise HTTPException(403, "此页面仅限平台运营人员")
    return PlatformActor(user)
