import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.modules.auth.schemas import UserView
from app.modules.auth.service import COOKIE, digest, now, provider
from app.modules.desktop.errors import fail
from app.modules.desktop.models import DesktopLogin, DeviceSession, DeviceToken
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop.schemas import (
    DesktopMe,
    DesktopOrganization,
    DesktopTokens,
    DeviceList,
    DeviceView,
    LoginProof,
)
from app.modules.desktop.session_policy import deadline, renew
from app.modules.members.models import Membership
from app.modules.members.service import membership_state
from app.modules.tenants.models import Installation, Tenant
from app.modules.users.models import LoginIdentity, User


@dataclass
class DesktopActor:
    session: DeviceSession
    identity: LoginIdentity
    user: User


def native(request: Request) -> NativeIdentity:
    return NativeIdentity(provider(request))


def native_request(request: Request) -> None:
    # Only the native main process calls these APIs. Do not mix browser authority.
    if (
        COOKIE in request.cookies
        or provider(request).settings.session_cookie_name in request.cookies
        or request.headers.get("origin")
    ):
        fail(401, "credential_type_mismatch", "此接口需要独立的桌面登录凭据")


def pkce(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


def device_view(
    session: DeviceSession, current: UUID | None = None, settings: Settings | None = None
) -> DeviceView:
    end = (
        deadline(session, settings)
        if settings
        else min(
            session.expires_at,
            session.idle_expires_at,
            session.absolute_expires_at or session.expires_at,
        )
    )
    status = "revoked" if session.revoked_at else ("expired" if end <= now() else "active")
    return DeviceView(
        id=session.id,
        name=session.name,
        os=session.os,
        app_version=session.app_version,
        created_at=session.created_at,
        last_active_at=session.last_active_at,
        expires_at=end,
        status=status,
        current=current == session.id,
    )


async def check_device(
    request: Request, db: AsyncSession, session: DeviceSession, *, upstream: bool = True
) -> DesktopActor:
    settings = provider(request).settings
    if session.revoked_at:
        fail(401, "device_revoked", "该设备已退出，请重新登录")
    if deadline(session, settings) <= now():
        fail(401, "session_expired", "桌面登录已过期，请重新登录")
    if session.client_id != settings.desktop_client_id or session.scope != "desktop:self":
        fail(403, "insufficient_scope", "此凭据不适用于当前客户端或操作")
    identity = await db.get(LoginIdentity, session.identity_id)
    if not identity or identity.issuer != settings.oidc_issuer:
        fail(401, "invalid_identity", "登录身份已失效")
    user = await db.get(User, identity.user_id)
    if not user:
        fail(401, "invalid_identity", "登录身份已失效")
    if upstream:
        await native(request).account_valid(identity.subject, session.authenticated_at)
    return DesktopActor(session, identity, user)


async def token_session(db: AsyncSession, raw: str, kind: str) -> tuple[DeviceToken, DeviceSession]:
    if len(raw) > 200 or not raw.startswith("avd_" + kind + "_"):
        fail(401, "invalid_credential", "桌面登录凭据无效")
    token = await db.get(DeviceToken, digest(raw))
    if not token or token.kind != kind:
        fail(401, "invalid_credential", "桌面登录凭据无效")
    session = await db.scalar(
        select(DeviceSession)
        .where(DeviceSession.id == token.session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not session:
        fail(401, "invalid_credential", "桌面登录凭据无效")
    await db.refresh(token)
    return token, session


async def desktop_actor(request: Request, db: AsyncSession) -> DesktopActor:
    native_request(request)
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        fail(401, "invalid_credential", "请登录桌面端")
    token, session = await token_session(db, authorization[7:], "access")
    actor = await check_device(request, db, session)
    if token.expires_at <= now():
        fail(401, "access_expired", "访问凭据已过期，请续期")
    session.last_active_at = now()
    if session.policy_mode == "strict":
        session.idle_expires_at = min(
            session.expires_at,
            now() + timedelta(minutes=provider(request).settings.desktop_idle_minutes),
        )
    return actor


async def login_proof(db: AsyncSession, payload: LoginProof) -> DesktopLogin:
    attempt = await db.scalar(
        select(DesktopLogin)
        .where(DesktopLogin.id == payload.attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not attempt
        or not secrets.compare_digest(attempt.state_hash, digest(payload.state.get_secret_value()))
        or not secrets.compare_digest(
            attempt.challenge, pkce(payload.code_verifier.get_secret_value())
        )
    ):
        fail(401, "invalid_login", "登录尝试验证失败，请重新发起")
    return attempt


async def issue_tokens(request: Request, db: AsyncSession, session: DeviceSession) -> DesktopTokens:
    settings = provider(request).settings
    stamp = now()
    renew(session, settings, stamp)
    access, refresh = (
        "avd_" + kind + "_" + secrets.token_urlsafe(32) for kind in ("access", "refresh")
    )
    access_expiry = min(
        stamp + timedelta(seconds=settings.desktop_access_seconds), session.expires_at
    )
    session.last_active_at = stamp
    if session.policy_mode == "strict":
        session.idle_expires_at = min(
            session.expires_at, stamp + timedelta(minutes=settings.desktop_idle_minutes)
        )
    db.add_all(
        [
            DeviceToken(
                token_hash=digest(access),
                session_id=session.id,
                kind="access",
                expires_at=access_expiry,
            ),
            DeviceToken(
                token_hash=digest(refresh),
                session_id=session.id,
                kind="refresh",
                expires_at=session.expires_at,
            ),
        ]
    )
    return DesktopTokens(
        access_token=access,
        refresh_token=refresh,
        session_policy=session.policy_mode,
        reauthenticate_at=session.absolute_expires_at,
        device_session_id=session.id,
        expires_in=max(0, int((access_expiry - stamp).total_seconds())),
        session_expires_at=session.expires_at,
        idle_expires_at=session.idle_expires_at,
    )


async def organization(
    db: AsyncSession, actor: DesktopActor, *, platform_edition: str = "community"
) -> tuple[Tenant | None, Membership | None]:
    if platform_edition == "community":
        install = await db.get(Installation, 1)
        if not install or not install.tenant_id:
            return None, None
        tenant_id = install.tenant_id
        query = select(Membership).where(
            Membership.tenant_id == tenant_id, Membership.user_id == actor.user.id
        )
    else:
        query = select(Membership).where(
            Membership.user_id == actor.user.id,
            Membership.source != "platform",
        )
        if actor.session.tenant_id is not None:
            query = query.where(Membership.tenant_id == actor.session.tenant_id)
        else:
            query = (
                query.join(Tenant)
                .where(Membership.status == "active", Tenant.active.is_(True))
                .order_by(Tenant.created_at, Tenant.id)
            )
            candidates = (await db.scalars(query.execution_options(populate_existing=True))).all()
            if len(candidates) != 1:
                return None, None
            actor.session.tenant_id = candidates[0].tenant_id
            return await db.get(
                Tenant, candidates[0].tenant_id, populate_existing=True
            ), candidates[0]
    member = await db.scalar(query.execution_options(populate_existing=True))
    if not member:
        return None, None
    return await db.get(Tenant, member.tenant_id, populate_existing=True), member


async def me(request: Request, db: AsyncSession, actor: DesktopActor) -> DesktopMe:
    tenant, member = await organization(
        db, actor, platform_edition=provider(request).settings.platform_edition
    )
    org = None
    if tenant and member:
        org = DesktopOrganization(
            tenant_id=tenant.id,
            membership_id=member.id,
            name=tenant.name,
            role=member.role,
            status=member.status if tenant.active else "unavailable",
            needs_login=bool(
                member.revoked_at and actor.session.authenticated_at <= member.revoked_at
            ),
        )
    choices = []
    if provider(request).settings.platform_edition == "saas":
        rows = (
            await db.execute(
                select(Membership, Tenant)
                .join(Tenant)
                .where(
                    Membership.user_id == actor.user.id,
                    Membership.source != "platform",
                    Membership.status.in_(["active", "paused"]),
                )
                .order_by(Tenant.name, Tenant.id)
            )
        ).all()
        choices = [
            DesktopOrganization(
                tenant_id=t.id,
                membership_id=m.id,
                name=t.name,
                role=m.role,
                status=m.status if t.active else "unavailable",
                needs_login=bool(m.revoked_at and actor.session.authenticated_at <= m.revoked_at),
            )
            for m, t in rows
        ]
    elif org is not None:
        choices = [org]
    user = UserView.model_validate(actor.user)
    if actor.user.avatar_version:
        user.avatar_url = "/api/v1/desktop/avatar?v=" + str(actor.user.avatar_version)
    return DesktopMe(
        user=user,
        organization=org,
        organizations=choices,
        organization_state=(
            "ready"
            if org and org.status == "active" and not org.needs_login
            else "blocked"
            if org
            else "selection_required"
            if choices
            else "no_available_organization"
        ),
        session_policy=actor.session.policy_mode,
        recovery_expires_at=deadline(actor.session, provider(request).settings),
        reauthenticate_at=actor.session.absolute_expires_at,
        device=device_view(actor.session, actor.session.id, provider(request).settings),
        account_url=provider(request).settings.app_url + "/account",
    )


async def require_organization(
    db: AsyncSession,
    actor: DesktopActor,
    tenant_id: UUID | None = None,
    *,
    platform_edition: str = "community",
) -> None:
    tenant, member = await organization(db, actor, platform_edition=platform_edition)
    if platform_edition == "saas" and actor.session.tenant_id is None and tenant is None:
        choices = await db.scalar(
            select(Membership.id)
            .join(Tenant)
            .where(
                Membership.user_id == actor.user.id,
                Membership.source != "platform",
                Membership.status == "active",
                Tenant.active.is_(True),
            )
            .limit(1)
        )
        if choices:
            fail(403, "organization_selection_required", "请选择当前组织后继续")
    if tenant_id and (not tenant or tenant.id != tenant_id):
        fail(403, "organization_denied", "没有此组织的访问权限")
    reason = membership_state(tenant, member, actor.session.authenticated_at)
    if reason:
        messages = {
            "no_membership": "请联系管理员加入组织",
            "organization_unavailable": "组织暂不可用",
            "member_suspended": "当前组织访问已暂停",
            "member_removed": "你已不在当前组织中",
            "reauthentication_required": "组织访问曾被暂停，请重新登录",
        }
        fail(401 if reason == "reauthentication_required" else 403, reason, messages[reason])


async def devices(
    db: AsyncSession, user_id: UUID, current: UUID | None = None, settings: Settings | None = None
) -> DeviceList:
    rows = (
        await db.scalars(
            select(DeviceSession)
            .join(LoginIdentity)
            .where(LoginIdentity.user_id == user_id)
            .order_by(DeviceSession.created_at.desc())
        )
    ).all()
    return DeviceList(items=[device_view(row, current, settings) for row in rows])


async def revoke(
    db: AsyncSession, user_id: UUID, session_id: UUID, *, platform_edition: str = "community"
) -> DeviceSession:
    row = await db.scalar(
        select(DeviceSession)
        .join(LoginIdentity)
        .where(DeviceSession.id == session_id, LoginIdentity.user_id == user_id)
        .with_for_update(of=DeviceSession)
        .execution_options(populate_existing=True)
    )
    if not row:
        fail(404, "device_not_found", "找不到此登录设备")
    if not row.revoked_at:
        row.revoked_at = now()
        await audit_device(db, row, "desktop.revoked", platform_edition=platform_edition)
    # Encrypted retry responses are no longer useful after revocation.
    from sqlalchemy import update

    await db.execute(
        update(DeviceToken).where(DeviceToken.session_id == row.id).values(response=None)
    )
    return row


async def audit_device(
    db: AsyncSession,
    session: DeviceSession,
    action: str,
    *,
    platform_edition: str = "community",
) -> None:
    from app.modules.audit.models import AuditEvent

    identity = await db.get(LoginIdentity, session.identity_id)
    if not identity:
        return
    user = await db.get(User, identity.user_id)
    if not user:
        return
    tenant_id: UUID | None
    if platform_edition == "community":
        install = await db.get(Installation, 1)
        if not install or not install.tenant_id:
            return
        tenant_id = install.tenant_id
    else:
        tenant_id = session.tenant_id
        if tenant_id is None:
            candidates = (
                await db.scalars(
                    select(Membership.tenant_id)
                    .join(Tenant)
                    .where(
                        Membership.user_id == user.id,
                        Membership.status == "active",
                        Membership.source != "platform",
                        Tenant.active.is_(True),
                    )
                )
            ).all()
            # A deployment-scoped device event must not be attributed to an arbitrary organization.
            tenant_id = candidates[0] if len(candidates) == 1 else None
        if not tenant_id:
            return
    member = await db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant_id)
    )
    if member:
        db.add(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=user.id,
                actor_name=user.name,
                action=action,
                target_id=session.id,
                target_name=session.name,
                details={"os": session.os, "client_id": session.client_id},
                result="success",
            )
        )
