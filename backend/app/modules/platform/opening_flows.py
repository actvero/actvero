from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import OrganizationOpeningFlow, WebSession
from app.modules.auth.service import session_for


async def current_flow(request: Request, db: AsyncSession) -> OrganizationOpeningFlow | None:
    raw = request.query_params.get("flow")
    if raw is None:
        return None
    try:
        flow_id = UUID(raw)
    except ValueError:
        raise HTTPException(400, "开通页面地址无效，请重新打开邀请") from None
    session = await session_for(request, db)
    row = await db.scalar(
        select(OrganizationOpeningFlow).where(
            OrganizationOpeningFlow.id == flow_id,
            OrganizationOpeningFlow.session_id == (session.id if session else None),
        )
    )
    if row is None:
        raise HTTPException(410, "开通页面已失效，请重新打开邀请或开通入口")
    return row


async def set_opening(
    request: Request, db: AsyncSession, session: WebSession, opening_id: UUID | None
) -> None:
    flow = await current_flow(request, db)
    if flow:
        flow.opening_id = opening_id
    else:
        # Preserve in-progress sessions from before per-tab contexts were introduced.
        session.organization_opening_id = opening_id


def return_path(flow: OrganizationOpeningFlow) -> str:
    path = "/organization-invite" if flow.invitation_id else "/organization-onboarding"
    return f"{path}?flow={flow.id}"
