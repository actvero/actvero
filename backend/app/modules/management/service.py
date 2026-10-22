import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import COOKIE, DB, digest, now, provider
from app.modules.desktop.errors import fail
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop.schemas import LoginProof
from app.modules.desktop.service import pkce
from app.modules.management.models import ManagementLogin, ManagementSession, ManagementToken
from app.modules.management.schemas import Organization, Tokens
from app.modules.management.settings import require_enabled
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor, ManagementBusinessActor, membership_state
from app.modules.tenants.models import Installation, PlatformOperator, Tenant
from app.modules.users.models import LoginIdentity, User


@dataclass
class ManagementActor:
    session: ManagementSession
    identity: LoginIdentity
    user: User


async def native_request(request: Request, db: DB) -> None:
    await require_enabled(request, db)
    settings = provider(request).settings
    if (
        COOKIE in request.cookies
        or settings.session_cookie_name in request.cookies
        or request.headers.get("origin")
    ):
        fail(401, "credential_type_mismatch", "此接口需要独立的 CLI 管理凭据")


def native(request: Request) -> NativeIdentity:
    settings = provider(request).settings
    return NativeIdentity(
        provider(request),
        client_id=settings.management_client_id,
        max_age_seconds=settings.management_reauthentication_days * 86400,
    )


async def check_session(
    request: Request, db: AsyncSession, row: ManagementSession
) -> ManagementActor:
    settings = provider(request).settings
    if row.revoked_at or min(row.expires_at, row.absolute_expires_at) <= now():
        fail(401, "session_expired", "CLI 登录已撤销或过期，请重新登录")
    if row.client_id != settings.management_client_id or row.scope not in {
        "management:read",
        "management:read management:write",
    }:
        fail(403, "insufficient_scope", "此凭据不适用于管理接口")
    identity = await db.get(LoginIdentity, row.identity_id)
    if not identity or identity.issuer != settings.oidc_issuer:
        fail(401, "invalid_identity", "登录身份已失效")
    user = await db.get(User, identity.user_id)
    if not user:
        fail(401, "invalid_identity", "登录身份已失效")
    await native(request).account_valid(identity.subject, row.authenticated_at)
    return ManagementActor(row, identity, user)


async def token_session(
    db: AsyncSession, raw: str, kind: str
) -> tuple[ManagementToken, ManagementSession]:
    if len(raw) > 200 or not raw.startswith("avm_" + kind + "_"):
        fail(401, "invalid_credential", "请使用 CLI 管理登录凭据")
    token = await db.get(ManagementToken, digest(raw))
    if not token or token.kind != kind:
        fail(401, "invalid_credential", "CLI 登录凭据无效")
    row = await db.scalar(
        select(ManagementSession)
        .where(ManagementSession.id == token.session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row:
        fail(401, "invalid_credential", "CLI 登录凭据无效")
    await db.refresh(token)
    return token, row


async def actor(request: Request, db: AsyncSession) -> ManagementActor:
    await native_request(request, db)
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        fail(401, "invalid_credential", "请先登录 CLI")
    token, row = await token_session(db, header[7:], "access")
    result = await check_session(request, db, row)
    if token.expires_at <= now():
        fail(401, "access_expired", "访问凭据已过期，请续期")
    row.last_active_at = now()
    return result


async def login_proof(db: AsyncSession, payload: LoginProof) -> ManagementLogin:
    row = await db.scalar(
        select(ManagementLogin)
        .where(ManagementLogin.id == payload.attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not row
        or not secrets.compare_digest(row.state_hash, digest(payload.state.get_secret_value()))
        or not secrets.compare_digest(row.challenge, pkce(payload.code_verifier.get_secret_value()))
    ):
        fail(401, "invalid_login", "CLI 登录证明无效")
    return row


async def issue_tokens(request: Request, db: AsyncSession, row: ManagementSession) -> Tokens:
    settings = provider(request).settings
    stamp = now()
    row.expires_at = min(
        row.absolute_expires_at, stamp + timedelta(days=settings.management_recovery_days)
    )
    row.last_active_at = stamp
    access, refresh = (
        "avm_" + kind + "_" + secrets.token_urlsafe(32) for kind in ("access", "refresh")
    )
    access_expiry = min(
        row.expires_at, stamp + timedelta(seconds=settings.management_access_seconds)
    )
    db.add_all(
        [
            ManagementToken(
                token_hash=digest(access),
                session_id=row.id,
                kind="access",
                expires_at=access_expiry,
            ),
            ManagementToken(
                token_hash=digest(refresh),
                session_id=row.id,
                kind="refresh",
                expires_at=row.expires_at,
            ),
        ]
    )
    return Tokens(
        scope=row.scope,
        access_token=access,
        refresh_token=refresh,
        session_id=row.id,
        expires_in=max(0, int((access_expiry - stamp).total_seconds())),
        server_time=stamp,
        session_expires_at=row.expires_at,
        reauthenticate_at=row.absolute_expires_at,
    )


async def organization(
    request: Request,
    db: AsyncSession,
    who: ManagementActor,
    org_id: UUID,
    *,
    require_admin: bool = False,
    write: bool = False,
) -> tuple[BusinessActor, Organization]:
    settings = provider(request).settings
    install = await db.get(Installation, 1)
    if settings.platform_edition == "community" and (not install or install.tenant_id != org_id):
        fail(403, "organization_denied", "没有此组织的管理权限")
    if write and "management:write" not in who.session.scope.split():
        fail(403, "insufficient_scope", "请使用 auth login --write 重新授权管理写入")
    query = select(Tenant).where(Tenant.id == org_id)
    if write:
        query = query.with_for_update()
    tenant = await db.scalar(query.execution_options(populate_existing=True))
    member = await db.scalar(
        select(Membership)
        .where(Membership.tenant_id == org_id, Membership.user_id == who.user.id)
        .execution_options(populate_existing=True)
    )
    # Platform access is explicit, live and restricted to assigned platform memberships.
    operator = None
    if settings.platform_edition == "saas" and member and member.source == "platform":
        operator = await db.scalar(
            select(PlatformOperator).where(
                PlatformOperator.user_id == who.user.id, PlatformOperator.status == "active"
            )
        )
    reason = membership_state(tenant, member, who.session.authenticated_at)
    authority = "membership"
    if operator and tenant and tenant.active and member and member.status == "active":
        reason = None
        authority = "platform"
        member = Membership(
            id=member.id,
            tenant_id=org_id,
            user_id=who.user.id,
            role="administrator",
            status="active",
            source="platform",
            version=member.version,
        )
    if reason:
        fail(401 if reason == "reauthentication_required" else 403, reason, "当前组织资格不可用")
    assert tenant is not None and member is not None
    if require_admin and member.role != "administrator":
        fail(403, "administrator_required", "此操作仅限该组织管理员")
    permissions = ["org.show", "org.permissions"]
    if member.role == "administrator":
        permissions += ["channels.list", "channels.show"]
        permissions += [f"{kind}.read" for kind in ("skills", "mcp", "experts")]
        if "management:write" in who.session.scope.split():
            permissions += [f"{kind}.write" for kind in ("skills", "mcp", "experts")]
    result = Organization(
        org_id=tenant.id,
        name=tenant.name,
        membership_id=member.id,
        role=member.role,
        authority=authority,
        available=True,
        permissions=permissions,
    )
    return ManagementBusinessActor(who.user, member, tenant, who.session.id), result
