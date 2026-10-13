"""Personal credentials resolve to current membership, never to a console session."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.access_keys.models import AccessKey, AccessKeyPolicy
from app.modules.access_keys.schemas import KeyGrantView, KeyPolicyView, KeyResource, KeyView
from app.modules.auth.service import digest, now, provider
from app.modules.desktop.errors import fail
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop.service import native_request
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor, membership_state
from app.modules.tenants.models import Installation, Tenant
from app.modules.users.models import LoginIdentity, User


@dataclass
class KeyActor(BusinessActor):
    key: AccessKey


def supplied(request: Request) -> bool:
    return request.headers.get("authorization", "").startswith("Bearer avk_")


async def policy(db: AsyncSession, tenant_id: UUID) -> KeyPolicyView:
    row = await db.get(AccessKeyPolicy, tenant_id, populate_existing=True)
    return (
        KeyPolicyView(version=row.version, enabled=row.enabled, max_days=row.max_days)
        if row
        else KeyPolicyView(version=0, enabled=True)
    )


def state(row: AccessKey, rules: KeyPolicyView, member: Membership) -> str:
    if row.revoked_at or row.deleted_at:
        return "revoked"
    if row.expires_at is not None and row.expires_at <= now():
        return "expired"
    if row.disabled:
        return "disabled"
    if (
        not rules.enabled
        or member.status != "active"
        or member.source == "platform"
        or member.revoked_at
        and row.authenticated_at <= member.revoked_at
        or rules.max_days
        and (
            row.expires_at is None
            or row.expires_at - row.created_at > timedelta(days=rules.max_days)
        )
    ):
        return "blocked"
    return "active"


def view(
    row: AccessKey,
    rules: KeyPolicyView,
    member: Membership,
    name: str,
    *,
    viewer_id: UUID | None = None,
) -> KeyView:
    return KeyView(
        can_reveal=(
            viewer_id == row.member_id
            and bool(row.sealed_secret)
            and state(row, rules, member) in ("active", "disabled")
        ),
        id=row.id,
        member_id=row.member_id,
        member_name=name,
        name=row.name,
        hint=row.hint,
        managed_disabled=row.managed_disabled,
        scope_mode=row.scope_mode,
        grants=[KeyGrantView.model_validate(g) for g in row.grants],
        status=state(row, rules, member),
        version=row.version,
        created_at=row.created_at,
        expires_at=row.expires_at,
        last_used_at=row.last_used_at,
    )


def permits(actor: BusinessActor, kind: str, resource_id: UUID | None, action: str) -> bool:
    if not isinstance(actor, KeyActor):
        return True
    # Scope is an upper bound only; each domain still checks current member authorization.
    if actor.key.scope_mode == "member":
        return kind in ("llm", "mcp") and action in ("read", "invoke")
    return actor.key.scope_mode == "selected" and any(
        g["kind"] == kind
        and (resource_id is None or g["resource_id"] == str(resource_id))
        and action in g["actions"]
        for g in actor.key.grants
    )


async def authorize(
    request: Request,
    db: AsyncSession,
    kind: str,
    resource_id: UUID | None = None,
    action: str = "read",
) -> KeyActor:
    native_request(request)
    header = request.headers.get("authorization", "")
    if not supplied(request) or len(header) > 210:
        fail(401, "invalid_access_key", "访问密钥无效")
    row = await db.scalar(
        select(AccessKey)
        .where(AccessKey.token_hash == digest(header[7:]))
        .execution_options(populate_existing=True)
    )
    if row is None:
        fail(401, "invalid_access_key", "访问密钥无效")
    member = await db.get(Membership, row.member_id, populate_existing=True)
    tenant = await db.get(Tenant, row.tenant_id, populate_existing=True)
    install = await db.get(Installation, 1, populate_existing=True)
    if (
        provider(request).settings.platform_edition == "community"
        and (not install or install.tenant_id != row.tenant_id)
    ) or membership_state(tenant, member, row.authenticated_at):
        fail(403, "membership_unavailable", "此密钥所属成员已失去访问资格")
    assert member is not None and tenant is not None
    if (
        member.tenant_id != row.tenant_id
        or state(row, await policy(db, row.tenant_id), member) != "active"
    ):
        fail(401, "access_key_unavailable", "访问密钥已停用、撤销、过期或不符合组织规则")
    identity = await db.get(LoginIdentity, row.identity_id)
    user = await db.get(User, member.user_id)
    if (
        not identity
        or not user
        or identity.user_id != user.id
        or identity.issuer != provider(request).settings.oidc_issuer
    ):
        fail(401, "invalid_identity", "登录身份已失效")
    await NativeIdentity(provider(request)).account_valid(identity.subject, row.authenticated_at)
    actor = KeyActor(user, member, tenant, row)
    if not permits(actor, kind, resource_id, action):
        fail(403, "key_scope_denied", "此密钥未获准访问该资源或操作")
    request.state.access_key_id = row.id
    return actor


async def resources(
    db: AsyncSession, actor: BusinessActor, kind: str, base: str
) -> list[KeyResource]:
    from app.modules.llm.catalog_schemas import CatalogInput
    from app.modules.llm.models import CatalogModel
    from app.modules.llm.runtime import visible as model_visible
    from app.modules.mcp.models import McpService
    from app.modules.mcp.service import visible as mcp_visible

    result = []
    if kind == "llm":
        rows = await db.scalars(
            select(CatalogModel)
            .where(CatalogModel.tenant_id == actor.tenant.id, CatalogModel.archived.is_(False))
            .order_by(CatalogModel.slug)
        )
        for row in rows:
            config = CatalogInput.model_validate(row.configuration)
            if model_visible(config, actor) and permits(actor, "llm", row.id, "read"):
                result.append(
                    KeyResource(
                        kind="llm",
                        id=row.id,
                        name=config.name,
                        identifier=config.slug,
                        endpoint=base + "/api/llm/v1",
                    )
                )
    else:
        services = await db.scalars(
            select(McpService)
            .where(McpService.tenant_id == actor.tenant.id)
            .order_by(McpService.name)
        )
        for svc in services:
            if mcp_visible(svc, actor) and permits(actor, "mcp", svc.id, "read"):
                result.append(
                    KeyResource(
                        kind="mcp",
                        id=svc.id,
                        name=svc.display_name or svc.name,
                        identifier=str(svc.id),
                        endpoint=base + "/api/mcp/services/" + str(svc.id),
                    )
                )
    return result
