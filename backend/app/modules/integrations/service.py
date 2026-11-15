from typing import Literal
from uuid import UUID

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import digest, now, provider
from app.modules.desktop.errors import fail
from app.modules.desktop.service import native_request
from app.modules.integrations.actor import ApplicationActor as ApplicationActor
from app.modules.integrations.models import IntegrationApplication, IntegrationKey
from app.modules.tenants.models import Installation, Tenant

KEY_PREFIX = "avi_"


Capability = Literal["models", "mcp", "skills", "experts", "knowledge"]
CAPABILITIES = ("models", "mcp", "skills", "experts", "knowledge")


def require(actor: ApplicationActor, capability: Capability) -> None:
    if not getattr(actor.application, f"{capability}_enabled"):
        fail(403, "application_scope_denied", "此应用未开启此项能力")


def supplied(request: Request) -> bool:
    return request.headers.get("authorization", "").startswith("Bearer " + KEY_PREFIX)


async def authorize(
    request: Request, db: AsyncSession, capability: Capability | None = None
) -> ApplicationActor:
    native_request(request)
    header = request.headers.get("authorization", "")
    if not supplied(request) or len(header) > 210:
        fail(401, "invalid_application_key", "请使用有效的应用密钥")
    key = await db.scalar(
        select(IntegrationKey)
        .where(IntegrationKey.token_hash == digest(header[7:]))
        .execution_options(populate_existing=True)
    )
    return await resolve(request, db, key, capability)


async def bound(
    request: Request,
    db: AsyncSession,
    key_id: UUID,
    capability: Capability,
    *,
    admitted_job: bool = False,
) -> ApplicationActor:
    key = await db.get(IntegrationKey, key_id, populate_existing=True)
    return await resolve(request, db, key, capability, admitted_job=admitted_job)


async def resolve(
    request: Request,
    db: AsyncSession,
    key: IntegrationKey | None,
    capability: Capability | None,
    *,
    admitted_job: bool = False,
) -> ApplicationActor:
    if key is None or (not admitted_job and (key.revoked_at or key.expires_at <= now())):
        fail(401, "invalid_application_key", "应用密钥无效、已撤销或已到期")
    application = await db.get(IntegrationApplication, key.application_id, populate_existing=True)
    if application is None or not application.enabled:
        fail(403, "application_disabled", "应用已停用")
    tenant = await db.get(Tenant, application.tenant_id, populate_existing=True)
    if tenant is None or not tenant.active:
        fail(403, "organization_unavailable", "组织不可用")
    if provider(request).settings.platform_edition == "community":
        install = await db.get(Installation, 1, populate_existing=True)
        if install is None or install.tenant_id != tenant.id:
            fail(403, "organization_unavailable", "组织不可用")
    actor = ApplicationActor(tenant, application, key)
    if capability:
        require(actor, capability)
    return actor
