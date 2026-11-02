from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, authenticate, provider
from app.modules.members.models import Membership
from app.modules.members.service import Access, membership_state, record
from app.modules.organization.schemas import OrganizationSettings, OrganizationSettingsUpdate
from app.modules.tenants.models import Installation, Tenant

router = APIRouter(prefix="/api/v1/enterprises/{tenant_id}/settings", tags=["organization"])


async def organization_admin(
    request: Request, db: DB, tenant_id: UUID, *, write: bool = False
) -> Access:
    session, _, user = await authenticate(request, db)
    installation_query = select(Installation).where(Installation.id == 1)
    if write:
        # Match the platform editor's lock order and serialize name uniqueness checks.
        installation_query = installation_query.with_for_update()
    install = await db.scalar(installation_query.execution_options(populate_existing=True))
    if provider(request).settings.platform_edition == "community" and (
        not install or install.tenant_id != tenant_id
    ):
        raise HTTPException(403, "你没有此组织的访问权限")
    query = select(Tenant).where(Tenant.id == tenant_id)
    if write:
        query = query.with_for_update()
    tenant = await db.scalar(query.execution_options(populate_existing=True))
    member = await db.scalar(
        select(Membership)
        .where(Membership.tenant_id == tenant_id, Membership.user_id == user.id)
        .execution_options(populate_existing=True)
    )
    reason = membership_state(tenant, member, session.authenticated_at)
    if reason:
        raise HTTPException(
            401 if reason == "reauthentication_required" else 403,
            "组织访问权限已更新，请重新登录"
            if reason == "reauthentication_required"
            else "你没有此组织的有效访问权限",
        )
    assert tenant is not None and member is not None
    if member.role != "administrator":
        raise HTTPException(403, "此操作仅限组织管理员")
    return Access(user, member, tenant, session)


@router.get("", response_model=OrganizationSettings)
async def settings(
    tenant_id: UUID, request: Request, response: Response, db: DB
) -> OrganizationSettings:
    actor = await organization_admin(request, db, tenant_id)
    response.headers["Cache-Control"] = "no-store"
    return OrganizationSettings.model_validate(actor.tenant)


@router.put("", response_model=OrganizationSettings)
async def update_settings(
    tenant_id: UUID,
    payload: OrganizationSettingsUpdate,
    request: Request,
    response: Response,
    db: DB,
    _: Mutation,
) -> OrganizationSettings:
    actor = await organization_admin(request, db, tenant_id, write=True)
    if actor.tenant.name != payload.expected_name:
        raise HTTPException(409, "组织信息已被其他管理员更新，请重新载入后再保存")
    if await db.scalar(
        select(Tenant.id).where(
            Tenant.id != tenant_id, func.lower(Tenant.name) == payload.name.casefold()
        )
    ):
        raise HTTPException(409, "组织名称已存在")
    if actor.tenant.name != payload.name:
        previous = actor.tenant.name
        actor.tenant.name = payload.name
        record(
            db,
            actor,
            "organization.settings.updated",
            tenant_id,
            payload.name,
            {"previous_name": previous},
        )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return OrganizationSettings.model_validate(actor.tenant)
