"""Shared device-bound resource tokens for native MCP and Skills access.

Reuse the existing token table; resource scope is checked on every request.
"""

import secrets
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import digest, limit, now, provider
from app.modules.desktop import service as desktop
from app.modules.desktop.errors import fail
from app.modules.desktop.models import DeviceSession
from app.modules.desktop_mcp.models import ResourceToken
from app.modules.desktop_mcp.schemas import ResourceTokenView
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor, membership_state
from app.modules.tenants.models import Installation, Tenant

CATALOG = "mcp:catalog"
CATALOG_SCOPE = "mcp:catalog mcp:connection"
INVOKE_SCOPE = "mcp:invoke"
SKILLS_CATALOG = "skills:catalog"
SKILLS_SCOPE = "skills:read skills:download"
EXPERTS_CATALOG = "experts:catalog"
EXPERTS_SCOPE = "experts:read"


def resource_scope(resource: str) -> str:
    if resource == EXPERTS_CATALOG:
        return EXPERTS_SCOPE
    if resource == SKILLS_CATALOG:
        return SKILLS_SCOPE
    return CATALOG_SCOPE if resource == CATALOG else INVOKE_SCOPE


@dataclass
class NativeActor(BusinessActor):
    device: DeviceSession


def endpoint(request: Request, resource: str) -> str:
    if resource == EXPERTS_CATALOG:
        return provider(request).settings.app_url.rstrip("/") + "/api/v1/desktop/experts"
    if resource == SKILLS_CATALOG:
        return provider(request).settings.app_url.rstrip("/") + "/api/v1/desktop/skills"
    path = (
        "/api/v1/desktop/mcp/connectors"
        if resource == CATALOG
        else "/api/mcp/services/" + resource.removeprefix("mcp:")
    )
    return provider(request).settings.app_url.rstrip("/") + path


async def business_actor(
    db: AsyncSession, actor: desktop.DesktopActor, *, platform_edition: str = "community"
) -> NativeActor:
    await desktop.require_organization(db, actor, platform_edition=platform_edition)
    tenant, member = await desktop.organization(db, actor, platform_edition=platform_edition)
    assert tenant is not None and member is not None
    return NativeActor(actor.user, member, tenant, actor.session)


async def issue(request: Request, db: AsyncSession, resource: str) -> ResourceTokenView:
    native = await desktop.desktop_actor(request, db)
    edition = provider(request).settings.platform_edition
    actor = await business_actor(db, native, platform_edition=edition)
    await limit(db, "mcp-resource:" + str(actor.device.id), 120, 60)
    native = await desktop.desktop_actor(request, db)
    actor = await business_actor(db, native, platform_edition=edition)
    if resource not in {CATALOG, SKILLS_CATALOG, EXPERTS_CATALOG}:
        from app.modules.desktop_mcp.service import get_service

        try:
            service_id = UUID(resource.removeprefix("mcp:"))
        except ValueError:
            fail(
                422,
                "invalid_resource",
                "资源格式应为 skills:catalog、mcp:catalog 或 mcp:<服务UUID>",
            )
        await get_service(db, actor, service_id)
        resource = "mcp:" + str(service_id)
    prefix = (
        "avx_" if resource == EXPERTS_CATALOG else "avs_" if resource == SKILLS_CATALOG else "avm_"
    )
    raw = prefix + secrets.token_urlsafe(32)
    expiry = min(now() + timedelta(seconds=600), actor.device.expires_at)
    scope = resource_scope(resource)
    db.add(
        ResourceToken(
            token_hash=digest(raw),
            device_id=actor.device.id,
            member_id=actor.member.id,
            resource=resource,
            scope=scope,
            expires_at=expiry,
        )
    )
    await db.commit()
    return ResourceTokenView(
        access_token=raw,
        resource=resource,
        scope=scope,
        expires_in=max(0, int((expiry - now()).total_seconds())),
        endpoint=endpoint(request, resource),
    )


async def authorize(
    request: Request, db: AsyncSession, resource: str = CATALOG, *, write: bool = False
) -> NativeActor:
    desktop.native_request(request)
    header = request.headers.get("authorization", "")
    raw = header.removeprefix("Bearer ")
    if not header.startswith(("Bearer avm_", "Bearer avs_", "Bearer avx_")) or len(raw) > 200:
        fail(401, "invalid_resource_token", "请使用此资源的访问令牌")
    token = await db.get(ResourceToken, digest(raw))
    if not token or token.expires_at <= now():
        fail(401, "resource_token_expired", "资源访问令牌无效或已过期，请重新申请")
    expected = resource_scope(resource)
    if token.resource != resource or token.scope != expected:
        fail(403, "resource_scope_mismatch", "此令牌不适用于当前资源")
    query = select(DeviceSession).where(DeviceSession.id == token.device_id)
    if write:
        query = query.with_for_update()
    device = await db.scalar(query.execution_options(populate_existing=True))
    if not device:
        fail(401, "device_revoked", "设备登录已失效")
    native = await desktop.check_device(request, db, device)
    if write:
        # Same tenant lock as Web publication / scope / membership mutations.
        if provider(request).settings.platform_edition == "community":
            installation = await db.get(Installation, 1)
            if installation and installation.tenant_id:
                await db.scalar(
                    select(Tenant).where(Tenant.id == installation.tenant_id).with_for_update()
                )
        else:
            tenant_id = await db.scalar(
                select(Membership.tenant_id).where(Membership.id == token.member_id)
            )
            if tenant_id:
                await db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
        # Locks may have waited; check expiry and all live authority again.
        if token.expires_at <= now():
            fail(401, "resource_token_expired", "资源访问令牌已过期，请重新申请")
        native = await desktop.check_device(request, db, device)
    actor = await actor_for_membership(db, native, token.member_id)
    if resource.startswith("mcp:"):
        request.state.mcp_device_id = device.id
    return actor


async def actor_for_membership(
    db: AsyncSession, native: desktop.DesktopActor, member_id: UUID
) -> NativeActor:
    # The token's membership fixes its organization. A later workspace switch
    # never retargets old tokens, even for users belonging to both organizations.
    member = await db.get(Membership, member_id, populate_existing=True)
    if member is None or member.user_id != native.user.id or member.source == "platform":
        fail(403, "organization_denied", "成员身份已变化，请重新申请访问")
    tenant = await db.get(Tenant, member.tenant_id, populate_existing=True)
    reason = membership_state(tenant, member, native.session.authenticated_at)
    if reason:
        fail(
            401 if reason == "reauthentication_required" else 403,
            reason,
            "此令牌的组织资格已不可用",
        )
    assert tenant is not None
    return NativeActor(native.user, member, tenant, native.session)
