from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message, OrganizationInvitationClaim, SetupResult
from app.modules.auth.service import DB, address_key, digest, limit, now
from app.modules.platform.onboarding import (
    invite_for,
    opening_for,
    policy,
    preview,
    send_verification,
    submit,
)
from app.modules.platform.schemas import OpeningPreview, OpeningSubmit
from app.modules.tenants.models import OrganizationInvitation

router = APIRouter(prefix="/api/v1/organization-invitations", tags=["organization-invitations"])


@router.post("/claim", response_model=Message)
async def claim(
    payload: OrganizationInvitationClaim, request: Request, db: DB, session: Mutation
) -> Message:
    await policy(request, db)
    await limit(db, address_key(request, "organization-invite-claim"), 20, 300)
    row = await db.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.token_hash == digest(payload.token or "")
        )
    )
    if (
        not row
        or row.status not in {"pending", "accepted"}
        or row.status == "pending"
        and row.expires_at <= now()
    ):
        raise HTTPException(410, "此邀请已过期或被撤销")
    if session.organization_invitation_id != row.id:
        session.organization_opening_id = None
    session.organization_invitation_id = row.id
    session.organization_invitation_hash = row.token_hash
    await db.commit()
    return Message(message="邀请已读取")


@router.get("/current", response_model=OpeningPreview)
async def current(request: Request, db: DB) -> OpeningPreview:
    return await preview(request, db, invitation=True)


@router.post("/activate", response_model=Message)
async def activate(request: Request, db: DB, session: Mutation) -> Message:
    return await send_verification(request, db, session, invitation=True)


@router.post("/complete", response_model=SetupResult)
async def complete(request: Request, db: DB, session: Mutation) -> SetupResult:
    opening = await opening_for(request, db, True)
    row = await invite_for(request, db)
    name = opening.organization_name if opening else row.organization_name
    if not name:
        raise HTTPException(422, "请填写组织名称")
    result = await submit(
        OpeningSubmit(organization_name=name, invitation=True), request, db, session
    )
    assert result.organization_id is not None
    return SetupResult(tenant_id=result.organization_id, name=result.organization_name)
