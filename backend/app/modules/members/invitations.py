import secrets
import smtplib
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from app.modules.audit.models import AuditEvent
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import InvitationClaim, InvitationPreview, Message, SetupResult
from app.modules.auth.service import DB, address_key, authenticate, digest, limit, now, provider
from app.modules.members.mail import send_invitation
from app.modules.members.models import Invitation, MemberCreation, Membership
from app.modules.members.schemas import DeliveryInput, InvitationPage, InvitationView, InviteInput
from app.modules.members.service import access, record
from app.modules.platform.mail_settings import effective_mail
from app.modules.tenants.models import Installation, Tenant
from app.modules.users.models import LoginIdentity

router = APIRouter(prefix="/api/v1", tags=["invitations"])


@router.get("/enterprises/{tenant_id}/invitations", response_model=InvitationPage)
async def invitations(
    tenant_id: UUID,
    request: Request,
    db: DB,
    page: int = Query(default=1, ge=1),
    q: str = Query(default="", max_length=200),
    status: str = "",
) -> InvitationPage:
    await access(request, db, tenant_id)
    filters = [Invitation.tenant_id == tenant_id]
    if q.strip():
        needle = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(or_(Invitation.email.ilike(needle), Invitation.name.ilike(needle)))
    if status == "expired":
        filters.append(
            or_(
                Invitation.status == "expired",
                (Invitation.status == "pending") & (Invitation.expires_at <= now()),
            )
        )
    elif status:
        filters.append(Invitation.status == status)
        if status == "pending":
            filters.append(Invitation.expires_at > now())
    total = await db.scalar(select(func.count()).select_from(Invitation).where(*filters)) or 0
    rows = (
        await db.scalars(
            select(Invitation)
            .where(*filters)
            .order_by(Invitation.created_at.desc(), Invitation.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    views = []
    for row in rows:
        view = InvitationView.model_validate(row)
        if row.status == "pending" and row.expires_at <= now():
            view.status = "expired"
        views.append(view)
    return InvitationPage(items=views, total=total, page=page)


@router.post("/enterprises/{tenant_id}/invitations", response_model=InvitationView)
async def invite(
    tenant_id: UUID, payload: InviteInput, request: Request, db: DB, _: Mutation
) -> InvitationView:
    settings = effective_mail(provider(request), await db.get(Installation, 1))
    if not settings.invitations_enabled:
        raise HTTPException(503, "邀请尚未配置完成，请联系部署维护人员配置邮件、身份管理与邀请期限")
    actor = await access(request, db, tenant_id, write=True)
    email = str(payload.email).casefold()
    existing = await db.get(Invitation, payload.request_id)
    if existing:
        if (
            existing.tenant_id != tenant_id
            or existing.created_by != actor.user.id
            or existing.email != email
        ):
            raise HTTPException(409, "请求标识已使用，请刷新后重试")
        return InvitationView.model_validate(existing)
    pending = await db.scalar(
        select(Invitation).where(
            Invitation.tenant_id == tenant_id,
            Invitation.email == email,
            Invitation.status == "pending",
        )
    )
    if pending:
        if pending.expires_at > now():
            raise HTTPException(409, "已有待接受邀请，请在邀请记录中查看或重发")
        pending.status = "expired"
        pending.token_ciphertext = None
        await db.flush()
    creating = await db.scalar(
        select(MemberCreation).where(
            MemberCreation.tenant_id == tenant_id,
            MemberCreation.email == email,
            MemberCreation.member_id.is_(None),
        )
    )
    if creating:
        raise HTTPException(409, "此邮箱正在直接创建，请在添加成员中完成原请求")
    subject, activation = await provider(request).prepare_user(email, payload.name.strip())
    identity = await db.scalar(
        select(LoginIdentity).where(
            LoginIdentity.issuer == settings.oidc_issuer, LoginIdentity.subject == subject
        )
    )
    if identity:
        member = await db.scalar(
            select(Membership).where(
                Membership.tenant_id == tenant_id, Membership.user_id == identity.user_id
            )
        )
        if member and member.status != "removed":
            raise HTTPException(409, "该成员已加入或已暂停，请前往成员详情处理")
    token = secrets.token_urlsafe(32)
    row = Invitation(
        id=payload.request_id,
        tenant_id=tenant_id,
        created_by=actor.user.id,
        email=email,
        name=payload.name.strip(),
        subject=subject,
        needs_activation=activation,
        token_hash=digest(token),
        token_ciphertext=provider(request).seal({"token": token}),
        expires_at=now() + timedelta(hours=settings.invitation_hours or 1),
    )
    db.add(row)
    record(db, actor, "invitation.created", row.id, email)
    await db.commit()
    # A durable invitation exists before SMTP. If delivery is interrupted it remains queryable.
    return await deliver(
        tenant_id, row.id, DeliveryInput(request_id=payload.request_id), request, db, _
    )


@router.post(
    "/enterprises/{tenant_id}/invitations/{invitation_id}/delivery", response_model=InvitationView
)
async def deliver(
    tenant_id: UUID,
    invitation_id: UUID,
    payload: DeliveryInput,
    request: Request,
    db: DB,
    _: Mutation,
) -> InvitationView:
    settings = effective_mail(provider(request), await db.get(Installation, 1))
    if not settings.invitations_enabled:
        raise HTTPException(503, "邀请邮件暂不可用，请联系部署维护人员")
    actor = await access(request, db, tenant_id, write=True)
    row = await db.scalar(
        select(Invitation)
        .where(Invitation.tenant_id == tenant_id, Invitation.id == invitation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row:
        raise HTTPException(404, "邀请不存在")
    if row.last_delivery_request_id == payload.request_id:
        return InvitationView.model_validate(row)
    if row.status not in {"pending", "expired"}:
        raise HTTPException(409, "邀请状态已变化，请刷新；已加入成员需在成员详情中管理")
    newer = await db.scalar(
        select(Invitation.id).where(
            Invitation.tenant_id == tenant_id,
            Invitation.email == row.email,
            Invitation.id != row.id,
            Invitation.status == "pending",
        )
    )
    if newer:
        raise HTTPException(409, "此邮箱已有另一份邀请，请使用最新邀请记录")
    joined = await db.scalar(
        select(Membership.id)
        .join(LoginIdentity, LoginIdentity.user_id == Membership.user_id)
        .where(
            Membership.tenant_id == tenant_id,
            Membership.status != "removed",
            LoginIdentity.issuer == provider(request).settings.oidc_issuer,
            LoginIdentity.subject == row.subject,
        )
    )
    if joined:
        raise HTTPException(409, "该账号已加入或已暂停，请前往成员详情处理")
    if row.last_sent_at and row.last_sent_at > now() - timedelta(seconds=60):
        raise HTTPException(429, "请稍后再发送邀请")
    if row.expires_at <= now() and not payload.replace:
        raise HTTPException(409, "邀请已过期，请使用重发生成新邀请")
    token = (
        secrets.token_urlsafe(32)
        if payload.replace
        else provider(request).unseal(row.token_ciphertext or "")["token"]
    )
    try:
        await send_invitation(settings, row.email, actor.tenant.name, token)
    except (OSError, smtplib.SMTPException):
        row.mail_status = "failed"
        record(db, actor, "invitation.sent", row.id, row.email, result="failed")
        await db.commit()
        return InvitationView.model_validate(row)
    if payload.replace:
        row.token_hash = digest(token)
        row.token_ciphertext = provider(request).seal({"token": token})
        row.expires_at = now() + timedelta(hours=provider(request).settings.invitation_hours or 1)
        row.status = "pending"
    row.last_sent_at = now()
    row.last_delivery_request_id = payload.request_id
    row.mail_status = "submitted"
    record(
        db,
        actor,
        "invitation.resent" if payload.replace else "invitation.sent",
        row.id,
        row.email,
        result="submitted",
    )
    await db.commit()
    return InvitationView.model_validate(row)


@router.post(
    "/enterprises/{tenant_id}/invitations/{invitation_id}/revoke", response_model=InvitationView
)
async def revoke(
    tenant_id: UUID, invitation_id: UUID, request: Request, db: DB, _: Mutation
) -> InvitationView:
    actor = await access(request, db, tenant_id, write=True)
    row = await db.scalar(
        select(Invitation)
        .where(Invitation.tenant_id == tenant_id, Invitation.id == invitation_id)
        .execution_options(populate_existing=True)
    )
    if not row:
        raise HTTPException(404, "邀请不存在")
    if row.status == "accepted":
        raise HTTPException(409, "对方已加入，请前往成员详情")
    if row.status != "revoked":
        row.status = "revoked"
        row.token_ciphertext = None
        record(db, actor, "invitation.revoked", row.id, row.email)
        await db.commit()
    return InvitationView.model_validate(row)


@router.post("/invitations/claim", response_model=Message)
async def claim(payload: InvitationClaim, request: Request, db: DB, session: Mutation) -> Message:
    await limit(db, address_key(request, "invite-claim"), 20, 300)
    row = await db.scalar(
        select(Invitation).where(Invitation.token_hash == digest(payload.token)).with_for_update()
    )
    if (
        not row
        or row.status in {"expired", "revoked"}
        or (row.status != "accepted" and row.expires_at <= now())
    ):
        raise HTTPException(404, "此邀请已失效，请联系企业管理员")
    tenant = await db.get(Tenant, row.tenant_id)
    if not tenant or not tenant.active:
        raise HTTPException(404, "此邀请所属组织不可用")
    if row.subject is None or not row.email:
        if payload.email is None or not payload.name or not payload.name.strip():
            session.invitation_id = row.id
            session.invitation_hash = row.token_hash
            await db.commit()
            return Message(message="邀请已读取，请填写账号信息")
        email = str(payload.email).casefold()
        subject, activation = await provider(request).prepare_user(email, payload.name.strip())
        identity = await db.scalar(
            select(LoginIdentity).where(
                LoginIdentity.issuer == provider(request).settings.oidc_issuer,
                LoginIdentity.subject == subject,
            )
        )
        if identity:
            member = await db.scalar(
                select(Membership).where(
                    Membership.tenant_id == row.tenant_id,
                    Membership.user_id == identity.user_id,
                    Membership.status != "removed",
                )
            )
            if member:
                raise HTTPException(409, "该账号已加入此组织")
        row.email = email
        row.name = payload.name.strip()
        row.subject = subject
        row.needs_activation = activation
    elif payload.email and str(payload.email).casefold() != row.email:
        raise HTTPException(409, "此邀请已绑定其他账号")
    session.invitation_id = row.id
    session.invitation_hash = row.token_hash
    await db.commit()
    return Message(message="邀请已读取，请验证账号")


@router.get("/invitations/current", response_model=InvitationPreview)
async def preview(request: Request, db: DB) -> InvitationPreview:
    from app.modules.auth.service import session_for

    session = await session_for(request, db)
    row = (
        await db.get(Invitation, session.invitation_id)
        if session and session.invitation_id
        else None
    )
    if (
        not row
        or not session
        or session.invitation_hash != row.token_hash
        or row.status in {"expired", "revoked"}
        or (row.status != "accepted" and row.expires_at <= now())
    ):
        return InvitationPreview(state="expired")
    tenant = await db.get(Tenant, row.tenant_id)
    if not tenant or not tenant.active:
        return InvitationPreview(state="unavailable")
    if row.subject is None or not row.email:
        return InvitationPreview(state="claim", tenant_name=tenant.name, expires_at=row.expires_at)
    if session is None or session.identity_id is None:
        return InvitationPreview(
            state="login",
            activation_required=row.needs_activation,
            tenant_name=tenant.name,
            expires_at=row.expires_at,
        )
    _, identity, user = await authenticate(request, db)
    if (
        row.subject != identity.subject
        or not identity.email_verified
        or (user.email or "").casefold() != row.email
    ):
        return InvitationPreview(state="mismatch")
    member = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == row.tenant_id, Membership.user_id == user.id
        )
    )
    if member and member.status == "paused":
        return InvitationPreview(state="paused")
    if row.status == "accepted" and (not member or member.status != "active"):
        return InvitationPreview(state="expired")
    return InvitationPreview(
        state="accepted" if row.status == "accepted" else "ready",
        tenant_name=tenant.name,
        email=row.email,
        role=row.role,
        expires_at=row.expires_at,
    )


@router.post("/invitations/activate", response_model=Message)
async def activate(request: Request, db: DB, session: Mutation) -> Message:
    row = await db.get(Invitation, session.invitation_id) if session.invitation_id else None
    if (
        not row
        or session.invitation_hash != row.token_hash
        or row.status != "pending"
        or row.expires_at <= now()
        or not row.subject
    ):
        raise HTTPException(404, "此邀请已失效")
    await limit(db, "activate:" + str(row.id), 3, 300)
    await provider(request).activation(row.subject)
    return Message(message="账号激活指引已提交发送，请查看邮件并完成后返回此页登录")


@router.post("/invitations/accept", response_model=SetupResult)
async def accept(request: Request, db: DB, _: Mutation) -> SetupResult:
    session, identity, user = await authenticate(request, db)
    row = await db.get(Invitation, session.invitation_id) if session.invitation_id else None
    if not row:
        raise HTTPException(404, "请重新打开邀请链接")
    tenant = await db.scalar(select(Tenant).where(Tenant.id == row.tenant_id).with_for_update())
    await db.refresh(row)
    if (
        not tenant
        or not tenant.active
        or session.invitation_hash != row.token_hash
        or row.status in {"expired", "revoked"}
    ):
        raise HTTPException(409, "此邀请已失效")
    if (
        row.subject != identity.subject
        or not identity.email_verified
        or (user.email or "").casefold() != row.email
    ):
        raise HTTPException(403, "此邀请不适用于当前账号")
    member = await db.scalar(
        select(Membership).where(
            Membership.tenant_id == row.tenant_id, Membership.user_id == user.id
        )
    )
    if member and member.status == "paused":
        raise HTTPException(403, "你的企业访问已暂停，请联系管理员")
    if row.status == "accepted":
        if member and member.status == "active":
            return SetupResult(tenant_id=tenant.id, name=tenant.name)
        raise HTTPException(409, "旧邀请不能恢复已结束的成员关系，请获取新邀请")
    if row.expires_at <= now():
        raise HTTPException(409, "此邀请已过期")
    if member is None:
        member = Membership(
            tenant_id=tenant.id,
            user_id=user.id,
            role=row.role,
            source="invitation",
        )
        db.add(member)
        await db.flush()
    elif member.status == "removed":
        member.status, member.role, member.source = "active", row.role, "invitation"
        member.version += 1
        member.joined_at = now()
    row.status = "accepted"
    row.accepted_by = user.id
    row.token_ciphertext = None
    db.add(
        AuditEvent(
            tenant_id=tenant.id,
            actor_id=user.id,
            actor_name=user.name,
            action="member.joined",
            target_id=member.id,
            target_name=user.name,
            details={},
        )
    )
    await db.commit()
    return SetupResult(tenant_id=tenant.id, name=tenant.name)
