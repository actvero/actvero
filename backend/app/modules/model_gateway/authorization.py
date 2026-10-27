"""Gateway credentials require real organization authority, including for operators."""

from fastapi import HTTPException, Request
from sqlalchemy import select

from app.modules.auth.service import DB
from app.modules.llm.router import administrator as organization_administrator
from app.modules.members.models import Membership
from app.modules.members.service import Access, membership_state


async def administrator(request: Request, db: DB, *, write: bool = False) -> Access:
    actor = await organization_administrator(request, db, write=write)
    member = await db.scalar(
        select(Membership)
        .where(Membership.id == actor.member.id, Membership.tenant_id == actor.tenant.id)
        .execution_options(populate_existing=True)
    )
    if (
        membership_state(actor.tenant, member, actor.session.authenticated_at)
        or member is None
        or member.role != "administrator"
    ):
        raise HTTPException(403, "仅本组织的有效管理员可以管理模型网关")
    return Access(actor.user, member, actor.tenant, actor.session)
