import base64
import secrets
import smtplib
from datetime import timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.modules.account.service import MAX_AVATAR_BYTES
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, digest, limit, now, provider
from app.modules.members.mail import (
    compose_mail,
    compose_member_invitation,
    compose_organization_invitation,
    send_mail,
)
from app.modules.members.models import Invitation, Membership
from app.modules.platform.access import platform_access
from app.modules.platform.branding import (
    DEFAULT_PLATFORM_NAME,
    asset_ids,
    logo_url,
    normalize_brand_image,
    render_asset,
)
from app.modules.platform.mail_settings import effective_mail, mail_view
from app.modules.platform.schemas import (
    CliSettingsUpdate,
    CliSettingsView,
    MailRecipient,
    MailSettingsUpdate,
    MailSettingsView,
    MailTemplateView,
    OpeningApplication,
    OpeningApplicationPage,
    OpeningDecision,
    OrganizationCreate,
    OrganizationCreated,
    OrganizationInvitationCreate,
    OrganizationInvitationLink,
    OrganizationInvitationPage,
    OrganizationUpdate,
    PlatformOrganization,
    PlatformOrganizationPage,
    PlatformSettingsUpdate,
    PlatformSettingsView,
    PortalSettings,
    RegistrationPolicy,
    RegistrationPolicyView,
)
from app.modules.platform.schemas import OrganizationInvitation as OrganizationInvitationView
from app.modules.tenants.models import BrandAsset, Installation, OrganizationOpening, Tenant
from app.modules.tenants.models import OrganizationInvitation as OrganizationInvitationModel
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/platform", tags=["platform"])


def cli_settings_view(request: Request, install: Installation) -> CliSettingsView:
    settings = provider(request).settings
    override = install.management_enabled
    return CliSettingsView(
        enabled=settings.management_enabled if override is None else override,
        source="environment" if override is None else "platform",
        server_url=settings.app_url,
        client_id=settings.management_client_id,
        issuer=settings.oidc_issuer,
    )


@router.get("/cli", response_model=CliSettingsView)
async def cli_settings(request: Request, response: Response, db: DB) -> CliSettingsView:
    await platform_access(request, db)
    install = await db.get(Installation, 1)
    if install is None:
        raise HTTPException(503, "平台尚未初始化")
    response.headers["Cache-Control"] = "no-store"
    return cli_settings_view(request, install)


@router.put("/cli", response_model=CliSettingsView)
async def update_cli_settings(
    payload: CliSettingsUpdate, request: Request, response: Response, db: DB, _: Mutation
) -> CliSettingsView:
    await platform_access(request, db)
    install = await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    if install is None:
        raise HTTPException(503, "平台尚未初始化")
    install.management_enabled = payload.enabled
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return cli_settings_view(request, install)


def platform_logo_url(request: Request, install: Installation) -> str | None:
    settings = provider(request).settings
    return logo_url(settings.app_url, install) or install.platform_logo_url


async def organization_view(db: DB, tenant: Tenant) -> PlatformOrganization:
    member_count = (
        await db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(Membership.tenant_id == tenant.id, Membership.source != "platform")
        )
        or 0
    )
    admin = (
        await db.execute(
            select(User.email, Membership.status)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.tenant_id == tenant.id,
                Membership.role == "administrator",
                Membership.source != "platform",
                Membership.status != "removed",
            )
            .order_by(Membership.joined_at, Membership.id)
            .limit(1)
        )
    ).first()
    pending = await db.scalar(
        select(Invitation.status)
        .where(
            Invitation.tenant_id == tenant.id,
            Invitation.role == "administrator",
            Invitation.status == "pending",
        )
        .order_by(Invitation.created_at.desc())
        .limit(1)
    )
    return PlatformOrganization(
        id=tenant.id,
        name=tenant.name,
        active=tenant.active,
        member_count=int(member_count),
        administrator_email=admin[0] if admin else None,
        administrator_status=(admin[1] if admin else ("pending" if pending else "unassigned")),
        created_at=tenant.created_at,
    )


def platform_settings_view(request: Request, install: Installation) -> PlatformSettingsView:
    settings = effective_mail(provider(request), install)
    return PlatformSettingsView(
        platform_name=install.platform_name or DEFAULT_PLATFORM_NAME,
        logo_url=platform_logo_url(request, install),
        smtp_configured=bool(settings.smtp_host and settings.smtp_from),
        smtp_host=settings.smtp_host,
        smtp_from=settings.smtp_from,
    )


@router.get("/site", response_model=PortalSettings)
async def public_site_settings(response: Response, db: DB) -> PortalSettings:
    """Anonymous homepage policy only; does not inspect or create a login session."""
    install = await db.get(Installation, 1)
    response.headers["Cache-Control"] = "no-store"
    return PortalSettings(portal_enabled=bool(install and install.portal_enabled))


@router.get("/portal", response_model=PortalSettings)
async def portal_settings(request: Request, response: Response, db: DB) -> PortalSettings:
    await platform_access(request, db)
    install = await db.get(Installation, 1)
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    response.headers["Cache-Control"] = "no-store"
    return PortalSettings(portal_enabled=install.portal_enabled)


@router.put("/portal", response_model=PortalSettings)
async def update_portal_settings(
    payload: PortalSettings, request: Request, response: Response, db: DB, _: Mutation
) -> PortalSettings:
    await platform_access(request, db)
    install = await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    install.portal_enabled = payload.portal_enabled
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return PortalSettings(portal_enabled=install.portal_enabled)


@router.get("/settings", response_model=PlatformSettingsView)
async def platform_settings(request: Request, db: DB) -> PlatformSettingsView:
    await platform_access(request, db)
    install = await db.get(Installation, 1)
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    return platform_settings_view(request, install)


@router.put("/settings", response_model=PlatformSettingsView)
async def update_platform_settings(
    payload: PlatformSettingsUpdate, request: Request, db: DB, _: Mutation
) -> PlatformSettingsView:
    await platform_access(request, db)
    install = await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    name = payload.platform_name.strip()
    if name != (install.platform_name or DEFAULT_PLATFORM_NAME):
        install.branding_revision = uuid4()
    install.platform_name = name
    if len(install.platform_name) < 1:
        raise HTTPException(422, "平台名称不能为空")
    await db.commit()
    return platform_settings_view(request, install)


@router.get("/mail", response_model=MailSettingsView)
async def get_mail_settings(request: Request, db: DB) -> MailSettingsView:
    await platform_access(request, db)
    install = await db.get(Installation, 1)
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    return mail_view(provider(request), install)


@router.put("/mail", response_model=MailSettingsView)
async def save_mail_settings(
    payload: MailSettingsUpdate, request: Request, db: DB, _: Mutation
) -> MailSettingsView:
    await platform_access(request, db)
    install = await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    current = mail_view(provider(request), install)
    old = effective_mail(provider(request), install)
    password = payload.password.get_secret_value() if payload.password else None
    destination_changed = (
        payload.host.casefold() != current.host.casefold()
        or payload.port != current.port
        or payload.security != current.security
        or payload.username != current.username
    )
    if payload.clear_password:
        password = None
    elif password is None and not destination_changed and old.smtp_password:
        password = old.smtp_password.get_secret_value()
    if payload.username and not password:
        raise HTTPException(422, "请输入授权码；更换服务器、端口、加密方式或账号时须重新填写")
    value = payload.model_dump(exclude={"password", "clear_password"})
    value["password"] = password
    if not payload.enabled and (
        install.registration_mode != "invite" or install.invitation_verify_email
    ):
        raise HTTPException(409, "请先关闭公开开通及邀请邮箱验证，再停用邮件服务")
    install.platform_mail_ciphertext = provider(request).seal(value)
    await provider(request).configure_mail(effective_mail(provider(request), install))
    await db.commit()
    return mail_view(provider(request), install)


@router.post("/mail/test", response_model=Message)
async def test_mail(payload: MailRecipient, request: Request, db: DB, _: Mutation) -> Message:
    actor = await platform_access(request, db)
    await limit(db, "platform-mail-test:" + str(actor.user.id), 3, 60)
    settings = effective_mail(provider(request), await db.get(Installation, 1))
    if not settings.smtp_host or not settings.smtp_from:
        raise HTTPException(409, "请先配置并启用邮件服务")
    message = compose_mail(
        settings,
        str(payload.email),
        "邮件服务测试",
        "这是一封测试邮件。收到此邮件表示当前地址可以接收平台邮件。",
        settings.app_url,
        "打开平台",
    )
    try:
        await send_mail(settings, message)
    except (OSError, smtplib.SMTPException):
        raise HTTPException(502, "发送失败，请检查 SMTP 地址、加密方式、账号和授权码") from None
    return Message(message="SMTP 已接收测试邮件，请检查收件箱或垃圾邮件")


@router.get("/mail/preview", response_model=MailTemplateView)
async def preview_mail(
    request: Request,
    db: DB,
    template: Literal["organization_invitation", "member_invitation"] = "organization_invitation",
) -> MailTemplateView:
    await platform_access(request, db)
    settings = effective_mail(provider(request), await db.get(Installation, 1))
    message = (
        compose_organization_invitation(
            settings, "preview@example.com", settings.app_url + "/organization-invite#preview"
        )
        if template == "organization_invitation"
        else compose_member_invitation(
            settings, "preview@example.com", "示例组织", settings.app_url + "/join#preview"
        )
    )
    html = message.get_body(preferencelist=("html",))
    assert html is not None
    return MailTemplateView(subject=str(message["Subject"]), html=html.get_content())


@router.put("/settings/logo", response_model=PlatformSettingsView)
async def upload_platform_logo(request: Request, db: DB, _: Mutation) -> PlatformSettingsView:
    await platform_access(request, db)
    media_type = request.headers.get("content-type", "").split(";", 1)[0]
    if media_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(415, "请选择 PNG、JPG 或 WebP 图片")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_AVATAR_BYTES:
            raise HTTPException(413, "Logo 文件不能超过 2 MB")
        data.extend(chunk)
    normalized = await run_in_threadpool(normalize_brand_image, base64.b64encode(data).decode())
    install = await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    install.branding_revision = uuid4()
    if (
        install.platform_logo_data
        and install.platform_logo_version
        and await db.get(BrandAsset, install.platform_logo_version) is None
    ):
        db.add(
            BrandAsset(
                id=install.platform_logo_version,
                data=install.platform_logo_data,
                media_type="image/webp",
            )
        )
    new_id = uuid4()
    db.add(BrandAsset(id=new_id, data=normalized, media_type="image/png"))
    install.branding_assets = {**(install.branding_assets or {}), "mark_light": str(new_id)}
    install.platform_logo_data = None
    install.platform_logo_version = None
    install.platform_logo_url = None
    await db.commit()
    return platform_settings_view(request, install)


@router.delete("/settings/logo", response_model=PlatformSettingsView)
async def remove_platform_logo(request: Request, db: DB, _: Mutation) -> PlatformSettingsView:
    await platform_access(request, db)
    install = await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    if (
        install.platform_logo_data
        and install.platform_logo_version
        and await db.get(BrandAsset, install.platform_logo_version) is None
    ):
        db.add(
            BrandAsset(
                id=install.platform_logo_version,
                data=install.platform_logo_data,
                media_type="image/webp",
            )
        )
    install.branding_revision = uuid4()
    install.branding_assets = {
        k: v
        for k, v in (install.branding_assets or {}).items()
        if k not in {"mark_light", "mark_dark"}
    }
    install.platform_logo_data = None
    install.platform_logo_version = None
    install.platform_logo_url = None
    await db.commit()
    return platform_settings_view(request, install)


@router.get("/logo", response_class=Response)
async def get_platform_logo(request: Request, db: DB) -> Response:
    install = await db.get(Installation, 1)
    version = request.query_params.get("v")
    try:
        chosen = (
            UUID(version)
            if version
            else (asset_ids(install).get("mark_light") if install else None)
        )
    except ValueError:
        raise HTTPException(404, "品牌图片不存在") from None
    asset = await db.get(BrandAsset, chosen) if chosen else None
    data = (
        asset.data
        if asset
        else (
            install.platform_logo_data
            if install and install.platform_logo_version == chosen
            else None
        )
    )
    if data is None:
        raise HTTPException(404, "尚未设置平台图标")
    content, media = await run_in_threadpool(render_asset, data, "legacy.webp")
    return Response(
        content, media_type=media, headers={"Cache-Control": "public, max-age=0, must-revalidate"}
    )


@router.get("/organizations", response_model=PlatformOrganizationPage)
async def organizations(request: Request, db: DB) -> PlatformOrganizationPage:
    await platform_access(request, db)
    tenants = (await db.scalars(select(Tenant).order_by(Tenant.created_at.desc(), Tenant.id))).all()
    return PlatformOrganizationPage(
        items=[await organization_view(db, tenant) for tenant in tenants],
        total=len(tenants),
    )


@router.post("/organization-invitations", response_model=OrganizationCreated)
async def create_organization_invitation(
    payload: OrganizationInvitationCreate, request: Request, db: DB, _: Mutation
) -> OrganizationCreated:
    settings = provider(request).settings
    if settings.platform_edition != "saas":
        raise HTTPException(404, "社区版不提供平台组织管理")
    actor = await platform_access(request, db)
    if (
        payload.recipient_email
        and not effective_mail(
            provider(request), await db.get(Installation, 1)
        ).identity_mail_enabled
    ):
        raise HTTPException(409, "请先配置邮件服务")
    token = secrets.token_urlsafe(32)
    row = OrganizationInvitationModel(
        id=uuid4(),
        created_by=actor.user.id,
        recipient_email=str(payload.recipient_email).casefold()
        if payload.recipient_email
        else None,
        token_hash=digest(token),
        expires_at=now() + timedelta(hours=payload.expires_in_hours),
    )
    row.token_ciphertext = provider(request).seal({"id": str(row.id), "token": token})
    db.add(row)
    await db.commit()
    mail_status = "link_only"
    if payload.recipient_email:
        try:
            await deliver_organization_invitation(
                row.id, MailRecipient(email=payload.recipient_email), request, db, _
            )
            mail_status = "sent"
        except HTTPException:
            mail_status = "failed"
    return OrganizationCreated(
        invitation=await organization_invitation_view(row),
        invite_url=f"{settings.app_url}/organization-invite#{token}",
        mail_status=mail_status,
    )


async def organization_invitation_view(
    row: OrganizationInvitationModel,
) -> OrganizationInvitationView:
    status = row.status
    if status == "pending" and row.expires_at <= now():
        status = "expired"
    return OrganizationInvitationView(
        id=row.id,
        status=status,
        organization_id=row.organization_id,
        organization_name=row.organization_name,
        expires_at=row.expires_at,
        created_at=row.created_at,
        can_copy=status == "pending" and bool(row.token_ciphertext),
        recipient_email=row.recipient_email,
    )


@router.get("/organization-invitations", response_model=OrganizationInvitationPage)
async def organization_invitations(request: Request, db: DB) -> OrganizationInvitationPage:
    await platform_access(request, db)
    rows = (
        await db.scalars(
            select(OrganizationInvitationModel).order_by(
                OrganizationInvitationModel.created_at.desc(), OrganizationInvitationModel.id
            )
        )
    ).all()
    return OrganizationInvitationPage(
        items=[await organization_invitation_view(row) for row in rows], total=len(rows)
    )


@router.post(
    "/organization-invitations/{invitation_id}/revoke",
    response_model=OrganizationInvitationView,
)
async def revoke_organization_invitation(
    invitation_id: UUID, request: Request, db: DB, _: Mutation
) -> OrganizationInvitationView:
    await platform_access(request, db)
    row = await db.scalar(
        select(OrganizationInvitationModel)
        .where(OrganizationInvitationModel.id == invitation_id)
        .with_for_update()
    )
    if not row:
        raise HTTPException(404, "邀请不存在")
    if row.status == "accepted":
        raise HTTPException(409, "组织已初始化，不能撤销")
    if row.status != "revoked":
        row.status = "revoked"
        row.token_ciphertext = None
        await db.commit()
    return await organization_invitation_view(row)


@router.post(
    "/organization-invitations/{invitation_id}/link", response_model=OrganizationInvitationLink
)
async def copy_organization_invitation(
    invitation_id: UUID, request: Request, db: DB, _: Mutation
) -> OrganizationInvitationLink:
    await platform_access(request, db)
    row = await db.scalar(
        select(OrganizationInvitationModel)
        .where(OrganizationInvitationModel.id == invitation_id)
        .with_for_update()
    )
    if not row or row.status != "pending" or row.expires_at <= now() or not row.token_ciphertext:
        raise HTTPException(409, "此邀请链接已不可用")
    secret = provider(request).unseal(row.token_ciphertext)
    if secret.get("id") != str(row.id) or digest(secret.get("token", "")) != row.token_hash:
        raise HTTPException(409, "此邀请链接已不可用")
    return OrganizationInvitationLink(
        invite_url=provider(request).settings.app_url + "/organization-invite#" + secret["token"]
    )


@router.post("/organization-invitations/{invitation_id}/delivery", response_model=Message)
async def deliver_organization_invitation(
    invitation_id: UUID, payload: MailRecipient, request: Request, db: DB, _: Mutation
) -> Message:
    actor = await platform_access(request, db)
    await limit(db, "platform-invite-mail:" + str(actor.user.id), 10, 300)
    link = await copy_organization_invitation(invitation_id, request, db, _)
    settings = effective_mail(provider(request), await db.get(Installation, 1))
    if not settings.smtp_host or not settings.smtp_from:
        raise HTTPException(409, "邮件服务未启用，你仍可以复制邀请链接")
    row = await db.get(OrganizationInvitationModel, invitation_id)
    assert row is not None
    email = str(payload.email).casefold()
    if row.recipient_email and row.recipient_email != email:
        raise HTTPException(409, "此邀请已绑定其他邮箱，请重新生成邀请")
    if row.email and row.email != email:
        raise HTTPException(409, "此邀请已被其他账号领取")
    row.recipient_email = email
    await db.commit()
    message = compose_organization_invitation(settings, email, link.invite_url)
    try:
        await send_mail(settings, message)
    except (OSError, smtplib.SMTPException):
        raise HTTPException(502, "发送失败，邀请仍然有效，可以重试或复制链接") from None
    return Message(message="SMTP 已接收邀请邮件；链接仍可复制或撤销")


@router.get("/registration", response_model=RegistrationPolicyView)
async def registration_policy(request: Request, db: DB) -> RegistrationPolicyView:
    await platform_access(request, db)
    install = await db.get(Installation, 1)
    assert install is not None
    return RegistrationPolicyView(
        mode=install.registration_mode,
        invitation_verify_email=install.invitation_verify_email,
        mail_enabled=effective_mail(provider(request), install).identity_mail_enabled,
    )


@router.put("/registration", response_model=RegistrationPolicyView)
async def save_registration(
    payload: RegistrationPolicy, request: Request, db: DB, _: Mutation
) -> RegistrationPolicyView:
    await platform_access(request, db)
    install = await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    assert install is not None
    mail = effective_mail(provider(request), install)
    if payload.mode != "invite" or payload.invitation_verify_email:
        if not mail.identity_mail_enabled:
            raise HTTPException(409, "请先配置并启用邮件服务")
        await provider(request).configure_mail(mail)
    install.registration_mode = payload.mode
    install.invitation_verify_email = payload.invitation_verify_email
    await db.commit()
    return await registration_policy(request, db)


@router.post("/organizations", response_model=PlatformOrganization)
async def create_own_organization(
    payload: OrganizationCreate, request: Request, db: DB, _: Mutation
) -> PlatformOrganization:
    from app.modules.platform.opening_service import create_organization

    actor = await platform_access(request, db)
    if payload.confirmed_user_id is not None and payload.confirmed_user_id != actor.user.id:
        raise HTTPException(409, "当前登录账号已变化，请重新确认管理员账号")
    tenant = await create_organization(
        db, payload.organization_name, actor.user, actor.user, {"source": "platform"}
    )
    await db.commit()
    return await organization_view(db, tenant)


@router.put("/organizations/{organization_id}", response_model=PlatformOrganization)
async def update_organization(
    organization_id: UUID, payload: OrganizationUpdate, request: Request, db: DB, _: Mutation
) -> PlatformOrganization:
    from app.modules.platform.opening_service import audit

    actor = await platform_access(request, db)
    await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
    row = await db.scalar(select(Tenant).where(Tenant.id == organization_id).with_for_update())
    if row is None:
        raise HTTPException(404, "组织不存在")
    if await db.scalar(
        select(Tenant.id).where(
            Tenant.id != row.id, func.lower(Tenant.name) == payload.organization_name.casefold()
        )
    ):
        raise HTTPException(409, "组织名称已存在")
    before = {
        "previous_name": row.name,
        "previous_active": str(row.active),
        "active": str(payload.active),
    }
    row.name = payload.organization_name
    row.active = payload.active
    audit(db, actor.user, row, "platform.organization.updated", before)
    await db.commit()
    return await organization_view(db, row)


@router.get("/applications", response_model=OpeningApplicationPage)
async def applications(request: Request, db: DB) -> OpeningApplicationPage:
    await platform_access(request, db)
    rows = (
        await db.execute(
            select(OrganizationOpening, User)
            .join(User, User.id == OrganizationOpening.applicant_id)
            .where(OrganizationOpening.mode == "approval", OrganizationOpening.status != "draft")
            .order_by(OrganizationOpening.created_at.desc())
        )
    ).all()
    return OpeningApplicationPage(
        items=[
            OpeningApplication(
                id=row.id,
                organization_name=row.organization_name,
                applicant_name=user.name,
                applicant_email=user.email,
                status=row.status,
                reason=row.reason,
                created_at=row.created_at,
                organization_id=row.organization_id,
            )
            for row, user in rows
        ],
        total=len(rows),
    )


@router.post("/applications/{application_id}/decision", response_model=Message)
async def decide(
    application_id: UUID, payload: OpeningDecision, request: Request, db: DB, _: Mutation
) -> Message:
    from app.modules.platform.opening_service import create_organization

    actor = await platform_access(request, db)
    row = await db.scalar(
        select(OrganizationOpening)
        .where(OrganizationOpening.id == application_id)
        .with_for_update()
    )
    if row is None or row.mode != "approval" or row.status == "draft":
        raise HTTPException(404, "申请不存在")
    target = "approved" if payload.approve else "rejected"
    if row.status != "pending":
        if row.status == target:
            return Message(message="申请已处理")
        raise HTTPException(409, "申请已处理，请刷新页面")
    if payload.approve:
        user = await db.get(User, row.applicant_id)
        assert user is not None
        if not row.subject or not await provider(request).user_enabled(row.subject):
            raise HTTPException(409, "申请账号已停用")
        tenant = await create_organization(
            db, row.organization_name, user, actor.user, {"application_id": str(row.id)}
        )
        row.organization_id = tenant.id
    elif not payload.reason.strip():
        raise HTTPException(422, "请填写拒绝原因")
    row.status = target
    row.reason = None if payload.approve else payload.reason.strip()
    row.reviewed_at = now()
    row.reviewed_by = actor.user.id
    await db.commit()
    return Message(message="已通过" if payload.approve else "已拒绝")
