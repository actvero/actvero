import secrets
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from starlette.responses import RedirectResponse

from app.modules.auth.models import OrganizationOpeningFlow, WebSession
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message, UserView
from app.modules.auth.service import (
    DB,
    address_key,
    authenticate,
    digest,
    limit,
    now,
    provider,
    session_for,
)
from app.modules.platform.mail_settings import effective_mail
from app.modules.platform.opening_flows import current_flow, return_path, set_opening
from app.modules.platform.opening_service import create_organization
from app.modules.platform.schemas import (
    OpeningDraft,
    OpeningFlowStart,
    OpeningFlowView,
    OpeningPreview,
    OpeningRegistration,
    OpeningSubmit,
)
from app.modules.tenants.models import Installation, OrganizationInvitation, OrganizationOpening
from app.modules.users.models import LoginIdentity, User

router = APIRouter(prefix="/api/v1/organization-onboarding", tags=["organization-onboarding"])


async def policy(request: Request, db: DB) -> Installation:
    if provider(request).settings.platform_edition != "saas":
        raise HTTPException(404, "社区版不提供组织开通")
    install = await db.get(Installation, 1)
    if not install or not install.platform_operator_user_id:
        raise HTTPException(409, "请先完成平台初始化")
    return install


async def invite_for(request: Request, db: DB, *, lock: bool = False) -> OrganizationInvitation:
    session = await session_for(request, db)
    flow = await current_flow(request, db)
    invitation_id = (
        flow.invitation_id if flow else (session.organization_invitation_id if session else None)
    )
    invitation_hash = (
        flow.invitation_hash
        if flow
        else (session.organization_invitation_hash if session else None)
    )
    query = select(OrganizationInvitation).where(OrganizationInvitation.id == invitation_id)
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query.execution_options(populate_existing=True))
    if (
        not row
        or not session
        or row.token_hash != invitation_hash
        or row.status not in {"pending", "accepted"}
        or row.status == "pending"
        and row.expires_at <= now()
    ):
        raise HTTPException(410, "此邀请已过期或被撤销")
    return row


async def context(
    request: Request, db: DB, invitation: bool, *, lock: bool = False
) -> tuple[str, bool, OrganizationInvitation | None]:
    install = await policy(request, db)
    flow = await current_flow(request, db)
    if flow and bool(flow.invitation_id) != invitation:
        raise HTTPException(400, "开通方式与当前页面不一致")
    row = await invite_for(request, db, lock=lock) if invitation else None
    mode = "invite" if row else install.registration_mode
    if not row and mode == "invite":
        raise HTTPException(403, "当前仅接受邀请开通，请联系平台运营人员")
    verify = (
        bool(row and (row.recipient_email or row.email or install.invitation_verify_email))
        or mode != "invite"
    )
    return mode, verify, row


async def opening_for(request: Request, db: DB, invitation: bool) -> OrganizationOpening | None:
    session = await session_for(request, db)
    flow = await current_flow(request, db)
    opening_id = flow.opening_id if flow else (session.organization_opening_id if session else None)
    opening = await db.get(OrganizationOpening, opening_id) if opening_id else None
    if opening and bool(opening.invitation_id) == invitation:
        return opening
    return None


async def verify_actor(
    request: Request,
    db: DB,
    required: bool,
    row: OrganizationInvitation | None,
    actor: tuple[WebSession, LoginIdentity, User] | None = None,
) -> tuple[WebSession, LoginIdentity, User]:
    session, identity, user = actor or await authenticate(request, db)
    expected = (row.recipient_email or row.email) if row else None
    if expected and (user.email or "").casefold() != expected.casefold():
        raise HTTPException(403, "请使用受邀邮箱对应的账号登录")
    if row and row.subject and row.subject != identity.subject:
        raise HTTPException(403, "请使用原受邀账号登录")
    if required and not identity.email_verified:
        identity.email_verified = await provider(request).verified_email(
            identity.subject, user.email or ""
        )
        if not identity.email_verified:
            raise HTTPException(409, "请先验证邮箱，再继续开通")
    return session, identity, user


@router.get("/current", response_model=OpeningPreview)
async def preview(
    request: Request, db: DB, invitation: bool = False, flow: UUID | None = None
) -> OpeningPreview:
    install = await policy(request, db)
    flow_context = await current_flow(request, db)
    opening = await opening_for(request, db, invitation)
    session = await session_for(request, db)
    user = identity = None
    if session and session.identity_id:
        _, identity, user = await authenticate(request, db)
    if not opening and user and not invitation:
        opening = await db.scalar(
            select(OrganizationOpening)
            .where(
                OrganizationOpening.applicant_id == user.id,
                OrganizationOpening.mode == "approval",
                OrganizationOpening.status.in_(["pending", "approved", "rejected"]),
            )
            .order_by(OrganizationOpening.created_at.desc())
            .limit(1)
        )
        if opening and session:
            await set_opening(request, db, session, opening.id)
            await db.commit()
    if opening and opening.status != "draft":
        if not user or opening.applicant_id != user.id:
            return OpeningPreview(state="login", mode=opening.mode)
        return OpeningPreview(
            state=opening.status,
            mode=opening.mode,
            organization_name=opening.organization_name,
            reason=opening.reason,
            organization_id=opening.organization_id,
        )
    if not invitation and install.registration_mode == "invite":
        return OpeningPreview(state="closed")
    try:
        mode, verify, row = await context(request, db, invitation)
    except HTTPException as error:
        if error.status_code == 410:
            return OpeningPreview(state="expired")
        raise
    expected = (row.recipient_email or row.email) if row else None
    if row and row.status == "accepted":
        return OpeningPreview(
            state="completed" if user and row.accepted_by == user.id else "used",
            organization_id=row.organization_id if user and row.accepted_by == user.id else None,
        )
    mismatch = bool(
        user
        and (
            (expected and expected != (user.email or "").casefold())
            or (row and row.subject and identity and row.subject != identity.subject)
        )
    )
    if opening and opening.subject and identity and opening.subject != identity.subject:
        mismatch = True
    return OpeningPreview(
        state="mismatch"
        if mismatch
        else ("login" if flow_context and opening and opening.subject and not user else "form"),
        account=UserView.model_validate(user) if user else None,
        mode=mode,
        recipient_email=expected,
        verify_email=verify and not bool(identity and identity.email_verified),
        organization_name=(
            flow_context.organization_name or (opening.organization_name if opening else "")
        )
        if flow_context
        else (opening.organization_name if opening else ""),
        resume=False,
    )


@router.post("/register", response_model=Message)
async def register(
    payload: OpeningRegistration,
    request: Request,
    db: DB,
    session: Mutation,
    flow: UUID | None = None,
) -> Message:
    await limit(db, address_key(request, "opening-register"), 10, 300)
    if session.identity_id:
        raise HTTPException(409, "你已登录，请直接开通组织")
    mode, verify, invite = await context(request, db, payload.invitation, lock=True)
    if invite and invite.status != "pending":
        raise HTTPException(409, "邀请已被使用")
    email = str(payload.email).casefold()
    if (
        invite
        and (invite.recipient_email or invite.email)
        and email != (invite.recipient_email or invite.email)
    ):
        raise HTTPException(403, "请使用受邀邮箱注册或登录")
    if (
        verify
        and not effective_mail(
            provider(request), await db.get(Installation, 1)
        ).identity_mail_enabled
    ):
        raise HTTPException(409, "邮件服务暂不可用，请联系平台运营人员")
    opening = await opening_for(request, db, payload.invitation)
    if opening is None or opening.status != "draft" or opening.email != email:
        opening = OrganizationOpening(
            mode=mode,
            invitation_id=invite.id if invite else None,
            organization_name=payload.organization_name,
            email=email,
            registration_marker=secrets.token_hex(32),
        )
        db.add(opening)
        await db.flush()
        await set_opening(request, db, session, opening.id)
    opening.organization_name = payload.organization_name
    await db.commit()
    assert opening.registration_marker is not None
    # Same admin-only marker as managed provisioning; passwords never reach storage or logs.
    try:
        subject, _ = await provider(request).create_managed_user(
            email,
            payload.name,
            payload.password.get_secret_value(),
            opening.registration_marker,
            "actvero_member",
            temporary=False,
        )
    except HTTPException as error:
        if error.status_code == 409:
            raise HTTPException(409, "请登录已有账号，或使用其他邮箱注册") from None
        raise
    opening.subject = subject
    await db.commit()
    return Message(message="账号已创建，请登录继续")


@router.post("/verify-email", response_model=Message)
async def send_verification(
    request: Request, db: DB, _: Mutation, invitation: bool = False, flow: UUID | None = None
) -> Message:
    mode, required, row = await context(request, db, invitation)
    _, identity, user = await verify_actor(request, db, False, row)
    await limit(db, "opening-verify:" + str(user.id), 3, 300)
    settings = effective_mail(provider(request), await db.get(Installation, 1))
    if not settings.identity_mail_enabled:
        raise HTTPException(409, "邮件服务暂不可用，请联系平台运营人员")
    if required:
        flow_context = await current_flow(request, db)
        await provider(request).verify_email(
            identity.subject,
            f"/api/v1/organization-onboarding/verified/{flow_context.id}"
            if flow_context
            else ("/organization-invite" if invitation else "/organization-onboarding"),
        )
    return Message(message="验证邮件已发送，请验证后返回此页继续")


@router.post("/submit", response_model=OpeningPreview)
async def submit(
    payload: OpeningSubmit, request: Request, db: DB, _: Mutation, flow: UUID | None = None
) -> OpeningPreview:
    # Authenticate before business locks: authentication commits refreshed tokens.
    actor = await authenticate(request, db)
    _, identity, user = actor
    # Session lock makes replay, double-click and callback recovery idempotent.
    session = await session_for(request, db, lock=True)
    if not session:
        raise HTTPException(401, "请先登录")
    flow_context = await current_flow(request, db)
    if session.identity_id != identity.id or (
        flow_context and payload.confirmed_user_id != user.id
    ):
        raise HTTPException(409, "当前登录账号已变化，请重新确认管理员账号")
    opening = await opening_for(request, db, payload.invitation)
    if opening and opening.status != "draft" and opening.applicant_id == user.id:
        return OpeningPreview(
            state=opening.status,
            mode=opening.mode,
            organization_id=opening.organization_id,
            organization_name=opening.organization_name,
            reason=opening.reason,
        )
    mode, verify, invite = await context(request, db, payload.invitation, lock=True)
    if invite and invite.status == "accepted":
        if invite.accepted_by != user.id:
            raise HTTPException(409, "邀请已被使用")
        return OpeningPreview(state="completed", organization_id=invite.organization_id)
    session, identity, user = await verify_actor(request, db, verify, invite, actor)
    if opening and opening.subject and opening.subject != identity.subject:
        raise HTTPException(403, "请使用刚创建的账号登录")
    if opening is None or opening.applicant_id not in (None, user.id):
        opening = OrganizationOpening(
            mode=mode,
            invitation_id=invite.id if invite else None,
            organization_name=payload.organization_name,
        )
        db.add(opening)
        await db.flush()
        await set_opening(request, db, session, opening.id)
    opening.organization_name = payload.organization_name
    opening.mode = mode
    opening.applicant_id = user.id
    opening.subject = identity.subject
    opening.email = user.email
    if mode == "approval":
        await db.scalar(select(User).where(User.id == user.id).with_for_update())
        pending = await db.scalar(
            select(OrganizationOpening).where(
                OrganizationOpening.applicant_id == user.id,
                OrganizationOpening.status == "pending",
                OrganizationOpening.id != opening.id,
            )
        )
        if pending:
            await set_opening(request, db, session, pending.id)
            await db.commit()
            return OpeningPreview(
                state="pending", mode=mode, organization_name=pending.organization_name
            )
        opening.status = "pending"
    else:
        tenant = await create_organization(
            db, payload.organization_name, user, user, {"mode": mode, "opening_id": str(opening.id)}
        )
        opening.organization_id = tenant.id
        opening.status = "completed"
        session.tenant_id = tenant.id
        if invite:
            invite.organization_id = tenant.id
            invite.organization_name = tenant.name
            invite.status = "accepted"
            invite.accepted_at = now()
            invite.accepted_by = user.id
            invite.token_ciphertext = None
    opening.registration_marker = None
    await db.commit()
    return OpeningPreview(
        state=opening.status,
        mode=mode,
        organization_name=opening.organization_name,
        organization_id=opening.organization_id,
    )


@router.post("/restart", response_model=Message)
async def restart(request: Request, db: DB, session: Mutation, flow: UUID | None = None) -> Message:
    await policy(request, db)
    flow_context = await current_flow(request, db)
    opening_id = flow_context.opening_id if flow_context else session.organization_opening_id
    if opening_id:
        row = await db.get(OrganizationOpening, opening_id)
        if row and row.status == "rejected":
            _, _, user = await authenticate(request, db)
            if row.applicant_id == user.id:
                draft = OrganizationOpening(
                    mode=row.mode,
                    organization_name=row.organization_name,
                    applicant_id=user.id,
                    email=user.email,
                )
                db.add(draft)
                await db.flush()
                await set_opening(request, db, session, draft.id)
                await db.commit()
                return Message(message="可以重新填写开通信息")
    await set_opening(request, db, session, None)
    await db.commit()
    return Message(message="可以重新填写开通信息")


@router.post("/flows", response_model=OpeningFlowView)
async def start_flow(
    payload: OpeningFlowStart, request: Request, db: DB, session: Mutation
) -> OpeningFlowView:
    await policy(request, db)
    await limit(db, address_key(request, "opening-flow"), 60, 300)
    invite = None
    if payload.invitation:
        if payload.token:
            invite = await db.scalar(
                select(OrganizationInvitation).where(
                    OrganizationInvitation.token_hash == digest(payload.token)
                )
            )
            if (
                not invite
                or invite.status not in {"pending", "accepted"}
                or (invite.status == "pending" and invite.expires_at <= now())
            ):
                raise HTTPException(410, "此邀请已过期或被撤销")
        else:
            # Upgrade an already-open pre-flow invitation without consuming it.
            invite = await invite_for(request, db)
    elif payload.token:
        raise HTTPException(400, "开通方式与当前页面不一致")
    row = OrganizationOpeningFlow(
        session_id=session.id,
        invitation_id=invite.id if invite else None,
        invitation_hash=invite.token_hash if invite else None,
    )
    legacy = (
        await db.get(OrganizationOpening, session.organization_opening_id)
        if session.organization_opening_id
        else None
    )
    if legacy and legacy.invitation_id == (invite.id if invite else None):
        row.opening_id = legacy.id
        row.organization_name = legacy.organization_name
    db.add(row)
    await db.commit()
    return OpeningFlowView(flow_id=row.id)


@router.put("/draft", response_model=Message)
async def save_draft(
    payload: OpeningDraft, request: Request, db: DB, _: Mutation, flow: UUID
) -> Message:
    row = await current_flow(request, db)
    assert row is not None
    row.organization_name = payload.organization_name.strip()
    await db.commit()
    return Message(message="已保存")


@router.post("/check-email", response_model=Message)
async def check_email(
    request: Request, db: DB, _: Mutation, invitation: bool = False, flow: UUID | None = None
) -> Message:
    mode, required, row = await context(request, db, invitation)
    await verify_actor(request, db, required, row)
    await db.commit()
    return Message(message="邮箱已验证，可以继续开通")


@router.get("/verified/{flow_id}", response_class=RedirectResponse)
async def verified_return(flow_id: UUID, request: Request, db: DB) -> RedirectResponse:
    session = await session_for(request, db)
    row = await db.scalar(
        select(OrganizationOpeningFlow).where(
            OrganizationOpeningFlow.id == flow_id,
            OrganizationOpeningFlow.session_id == (session.id if session else None),
        )
    )
    destination = return_path(row) if row else f"/organization-onboarding?flow={flow_id}"
    return RedirectResponse(destination, status_code=303)
