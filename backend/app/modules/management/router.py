import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

import httpx
import httpx2
from authlib.common.errors import AuthlibBaseError
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.security import HTTPBearer
from joserfc.errors import JoseError
from sqlalchemy import func, select, update

from app.modules.auth.identity import resolve_identity
from app.modules.auth.schemas import Message, UserView
from app.modules.auth.service import DB, address_key, digest, limit, now, provider
from app.modules.desktop.errors import fail
from app.modules.management import schemas as s
from app.modules.management import service
from app.modules.management.models import ManagementLogin, ManagementSession, ManagementToken
from app.modules.members.models import Membership
from app.modules.members.service import membership_state
from app.modules.platform.branding import DEFAULT_PLATFORM_NAME
from app.modules.tenants.models import Installation, PlatformOperator, Tenant
from app.modules.users.models import User

bearer = HTTPBearer(scheme_name="ManagementAccess", auto_error=False)
router = APIRouter(
    prefix="/api/v1/management",
    tags=["management"],
    dependencies=[Depends(service.native_request)],
)
BEARER = [Depends(bearer)]


@router.get("/metadata", response_model=s.Metadata)
async def metadata(request: Request, db: DB) -> s.Metadata:
    install = await db.get(Installation, 1)
    if not install:
        fail(503, "installation_unavailable", "平台尚未初始化")
    settings = provider(request).settings
    return s.Metadata(
        instance_id=install.instance_id,
        platform_name=install.platform_name or DEFAULT_PLATFORM_NAME,
        client_id=settings.management_client_id,
        issuer=settings.oidc_issuer,
        access_seconds=settings.management_access_seconds,
        recovery_days=settings.management_recovery_days,
        reauthentication_days=settings.management_reauthentication_days,
    )


@router.post("/login/start", response_model=s.LoginAttempt)
async def start(payload: s.StartLogin, request: Request, db: DB) -> s.LoginAttempt:
    await limit(db, address_key(request, "management-login"), 30, 300)
    if payload.authorization_version == 1 and "management:write" in payload.scope.split():
        fail(409, "client_upgrade_required", "写权限需要浏览器授权，请升级 CLI 后重新登录")
    if payload.target == "platform" and payload.authorization_version != 3:
        fail(409, "client_upgrade_required", "平台管理需要新版浏览器授权")
    if payload.scope == "platform:read" and payload.target != "platform":
        fail(422, "invalid_scope", "平台凭据须选择平台授权")
    state, nonce = (secrets.token_urlsafe(32) for _ in range(2))
    attempt = ManagementLogin(
        state_hash=digest(state),
        nonce=nonce,
        challenge=payload.code_challenge,
        redirect_uri=payload.redirect_uri,
        name=payload.device_name,
        scope="management:read",
        authorization_version=payload.authorization_version,
        target=payload.target,
        reauthenticate=payload.reauthenticate,
        expires_at=now() + timedelta(minutes=5),
    )
    db.add(attempt)
    await db.flush()
    if payload.authorization_version >= 2:
        url = (
            provider(request).settings.app_url
            + "/cli/authorize#"
            + urlencode({"attempt_id": str(attempt.id), "state": state})
        )
    else:
        url = await service.native(request).authorization(
            payload.redirect_uri, state, nonce, payload.code_challenge, payload.reauthenticate
        )
    await db.commit()
    return s.LoginAttempt(
        attempt_id=attempt.id,
        authorization_url=url,
        state=state,
        issuer=provider(request).settings.oidc_issuer,
        expires_at=attempt.expires_at,
    )


async def cached(request: Request, db: DB, sealed: str) -> s.Tokens:
    result = s.Tokens.model_validate(provider(request).unseal(sealed))
    token = await db.get(ManagementToken, digest(result.access_token))
    if not token:
        fail(409, "retry_expired", "登录恢复窗口已结束")
    result.expires_in = max(0, int((token.expires_at - now()).total_seconds()))
    result.server_time = now()
    return result


@router.post("/login/exchange", response_model=s.Tokens)
async def exchange(payload: s.ExchangeLogin, request: Request, db: DB) -> s.Tokens:
    await limit(db, address_key(request, "management-exchange"), 60, 300)
    settings = provider(request).settings
    if payload.issuer != settings.oidc_issuer:
        fail(401, "invalid_login", "登录来源与平台不一致")
    attempt = await service.login_proof(db, payload)
    if attempt.cancelled:
        fail(401, "login_cancelled", "登录已取消")
    if attempt.consumed:
        session = await db.scalar(
            select(ManagementSession)
            .where(ManagementSession.id == attempt.session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if session:
            await service.check_session(request, db, session)
        if (
            session
            and attempt.code_hash == digest(payload.code.get_secret_value())
            and attempt.response
            and attempt.response_until
            and attempt.response_until > now()
        ):
            result = await cached(request, db, attempt.response)
            refresh = await db.get(ManagementToken, digest(result.refresh_token))
            if refresh and not refresh.used_at:
                await db.commit()
                return result
        fail(409, "login_consumed", "登录结果已使用，请使用已保存的凭据")
    if attempt.expires_at <= now():
        fail(401, "login_expired", "登录尝试已过期")
    if attempt.authorization_version >= 2:
        if (
            not attempt.approved_at
            or not attempt.approved_identity_id
            or (attempt.target != "platform" and not attempt.authorized_org_ids)
        ):
            fail(403, "consent_required", "请先在浏览器确认 CLI 的组织和权限")
    elif "management:write" in attempt.scope.split():
        fail(403, "consent_required", "写权限需要浏览器授权，请升级 CLI 后重新登录")
    attempt.consumed = True
    try:
        claims = await service.native(request).exchange(
            payload.code.get_secret_value(),
            payload.code_verifier.get_secret_value(),
            attempt.nonce,
            attempt.redirect_uri,
        )
        authenticated = datetime.fromtimestamp(claims["auth_time"], UTC)
        await service.native(request).account_valid(str(claims["sub"]), authenticated)
    except (httpx.HTTPError, httpx2.HTTPError):
        await db.commit()
        fail(503, "identity_unavailable", "身份服务暂不可用，请重新发起登录")
    except (AuthlibBaseError, JoseError, HTTPException, ValueError, KeyError, TypeError):
        await db.commit()
        fail(401, "invalid_login", "登录验证失败，请重新发起")
    identity, _ = await resolve_identity(db, settings.oidc_issuer, claims)
    if attempt.authorization_version >= 2 and identity.id != attempt.approved_identity_id:
        await db.commit()
        fail(403, "consent_identity_mismatch", "登录账号与授权账号不同，请重新发起授权")
    stamp = now()
    cap = authenticated + timedelta(days=settings.management_reauthentication_days)
    if cap <= stamp:
        await db.commit()
        fail(401, "reauthentication_required", "请重新验证登录身份")
    row = ManagementSession(
        identity_id=identity.id,
        client_id=settings.management_client_id,
        scope=attempt.scope,
        authorized_org_ids=attempt.authorized_org_ids,
        platform_permissions=attempt.platform_permissions,
        name=attempt.name,
        authenticated_at=authenticated,
        created_at=stamp,
        last_active_at=stamp,
        expires_at=min(cap, stamp + timedelta(days=settings.management_recovery_days)),
        absolute_expires_at=cap,
    )
    if row.authorized_org_ids is not None:
        user = await db.get(User, identity.user_id)
        assert user is not None
        for org_id in row.authorized_org_ids:
            await service.organization(
                request,
                db,
                service.ManagementActor(row, identity, user),
                UUID(org_id),
                require_admin=True,
            )
    if row.scope == "platform:read":
        await service.platform_operator(request, db, identity.user_id)
    db.add(row)
    await db.flush()
    result = await service.issue_tokens(request, db, row)
    attempt.session_id = row.id
    attempt.code_hash = digest(payload.code.get_secret_value())
    attempt.response = provider(request).seal(result.model_dump(mode="json"))
    attempt.response_until = stamp + timedelta(minutes=2)
    await db.commit()
    return result


@router.post("/login/cancel", response_model=Message)
async def cancel(payload: s.LoginProof, request: Request, db: DB) -> Message:
    await limit(db, address_key(request, "management-cancel"), 60, 300)
    attempt = await service.login_proof(db, payload)
    attempt.cancelled, attempt.response = True, None
    if attempt.session_id:
        row = await db.scalar(
            select(ManagementSession)
            .where(ManagementSession.id == attempt.session_id)
            .with_for_update()
        )
        if row:
            row.revoked_at = row.revoked_at or now()
    await db.commit()
    return Message(message="已取消 CLI 登录")


@router.post("/refresh", response_model=s.Tokens)
async def refresh(payload: s.RefreshSession, request: Request, db: DB) -> s.Tokens:
    await limit(db, address_key(request, "management-refresh"), 120, 300)
    token, row = await service.token_session(
        db, payload.refresh_token.get_secret_value(), "refresh"
    )
    await service.check_session(request, db, row)
    if token.expires_at <= now():
        fail(401, "session_expired", "CLI 登录已过期")
    if token.used_at:
        successor = (
            await db.get(ManagementToken, token.successor_hash) if token.successor_hash else None
        )
        if (
            token.request_id == payload.request_id
            and token.response
            and token.response_until
            and token.response_until > now()
            and successor
            and not successor.used_at
        ):
            result = await cached(request, db, token.response)
            await db.commit()
            return result
        fail(409, "refresh_replayed", "续期结果无法恢复，请重新登录")
    await db.execute(
        update(ManagementToken)
        .where(
            ManagementToken.session_id == row.id, ManagementToken.successor_hash == token.token_hash
        )
        .values(response=None, acknowledged_at=now())
    )
    result = await service.issue_tokens(request, db, row)
    token.used_at, token.request_id = now(), payload.request_id
    token.successor_hash = digest(result.refresh_token)
    token.response_until = min(row.expires_at, now() + timedelta(days=7))
    result.refresh_request_id, result.recovery_until = payload.request_id, token.response_until
    token.response = provider(request).seal(result.model_dump(mode="json"))
    await db.commit()
    return result


@router.post("/refresh/acknowledge", response_model=Message)
async def acknowledge(payload: s.RefreshAcknowledgement, request: Request, db: DB) -> Message:
    token, row = await service.token_session(
        db, payload.refresh_token.get_secret_value(), "refresh"
    )
    await service.check_session(request, db, row)
    parent = await db.scalar(
        select(ManagementToken).where(
            ManagementToken.session_id == row.id,
            ManagementToken.successor_hash == token.token_hash,
            ManagementToken.request_id == payload.request_id,
        )
    )
    if not parent:
        fail(409, "refresh_acknowledgement_mismatch", "续期确认不匹配")
    parent.response, parent.acknowledged_at = None, parent.acknowledged_at or now()
    await db.commit()
    return Message(message="已确认凭据保存")


@router.post("/logout", response_model=Message)
async def logout(payload: s.LogoutSession, request: Request, db: DB) -> Message:
    _, row = await service.token_session(db, payload.refresh_token.get_secret_value(), "refresh")
    row.revoked_at = row.revoked_at or now()
    await db.execute(
        update(ManagementToken).where(ManagementToken.session_id == row.id).values(response=None)
    )
    await db.execute(
        update(ManagementLogin).where(ManagementLogin.session_id == row.id).values(response=None)
    )
    await db.commit()
    return Message(message="已退出此 CLI 会话")


@router.get("/me", response_model=s.Me, dependencies=BEARER)
async def me(request: Request, db: DB) -> s.Me:
    who = await service.actor(request, db)
    result = s.Me(
        scope=who.session.scope,
        platform_permissions=who.session.platform_permissions,
        authorized_org_ids=(
            [UUID(value) for value in who.session.authorized_org_ids]
            if who.session.authorized_org_ids is not None
            else None
        ),
        user=UserView.model_validate(who.user),
        session_id=who.session.id,
        session_expires_at=who.session.expires_at,
        reauthenticate_at=who.session.absolute_expires_at,
    )
    await db.commit()
    return result


@router.get("/organizations", response_model=s.Organizations, dependencies=BEARER)
async def organizations(
    request: Request, db: DB, page: int = Query(default=1, ge=1)
) -> s.Organizations:
    who = await service.actor(request, db)
    if who.session.scope == "platform:read":
        fail(403, "credential_type_mismatch", "请使用组织登录查询组织资源")
    settings = provider(request).settings
    filters = [Membership.user_id == who.user.id, Membership.status != "removed"]
    if who.session.authorized_org_ids is not None:
        filters.append(
            Membership.tenant_id.in_([UUID(value) for value in who.session.authorized_org_ids])
        )
    if settings.platform_edition == "community":
        install = await db.get(Installation, 1)
        filters.append(Membership.tenant_id == (install.tenant_id if install else None))
    query = select(Membership, Tenant).join(Tenant).where(*filters)
    total = await db.scalar(
        select(func.count()).select_from(Membership).join(Tenant).where(*filters)
    )
    rows = (
        await db.execute(query.order_by(Tenant.name, Tenant.id).offset((page - 1) * 50).limit(50))
    ).all()
    operator = (
        await db.scalar(
            select(PlatformOperator).where(
                PlatformOperator.user_id == who.user.id, PlatformOperator.status == "active"
            )
        )
        if settings.platform_edition == "saas"
        else None
    )
    items = []
    for member, tenant in rows:
        reason = membership_state(tenant, member, who.session.authenticated_at)
        platform = bool(operator and member.source == "platform")
        if platform and tenant.active and member.status == "active":
            reason = None
        role = "administrator" if platform else member.role
        permissions = ["org.show", "org.permissions"] if reason is None else []
        if reason is None and role == "administrator":
            permissions += [
                "channels.list",
                "channels.show",
                "skills.read",
                "mcp.read",
                "experts.read",
            ]
            if "management:write" in who.session.scope.split():
                permissions += ["skills.write", "mcp.write", "experts.write"]
        items.append(
            s.Organization(
                org_id=tenant.id,
                name=tenant.name,
                membership_id=member.id,
                role=role,
                authority="platform" if platform else "membership",
                available=reason is None,
                reason=reason,
                permissions=permissions,
            )
        )
    await db.commit()
    return s.Organizations(items=items, total=total or 0, page=page)


@router.get("/organizations/{org_id}", response_model=s.Organization, dependencies=BEARER)
@router.get(
    "/organizations/{org_id}/permissions", response_model=s.Organization, dependencies=BEARER
)
async def organization(org_id: UUID, request: Request, db: DB) -> s.Organization:
    who = await service.actor(request, db)
    _, result = await service.organization(request, db, who, org_id)
    await db.commit()
    return result


@router.get("/organizations/{org_id}/channels", response_model=s.ChannelList, dependencies=BEARER)
async def channels(
    org_id: UUID,
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=100),
    state: Literal["current", "archived", "all"] = "current",
    page: int = Query(default=1, ge=1),
) -> s.ChannelList:
    from app.modules.llm.router import channel_page

    who = await service.actor(request, db)
    business, org = await service.organization(request, db, who, org_id, require_admin=True)
    result = await channel_page(db, business, q=q, state=state, page=page)
    await db.commit()
    return s.ChannelList(organization=org, result=result)


@router.get(
    "/organizations/{org_id}/channels/{channel_id}",
    response_model=s.ChannelResult,
    dependencies=BEARER,
)
async def channel(org_id: UUID, channel_id: UUID, request: Request, db: DB) -> s.ChannelResult:
    from app.modules.llm.router import channel_detail

    who = await service.actor(request, db)
    business, org = await service.organization(request, db, who, org_id, require_admin=True)
    result = await channel_detail(db, business, channel_id)
    await db.commit()
    return s.ChannelResult(organization=org, result=result)
