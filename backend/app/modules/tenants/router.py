import secrets

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message, SetupRegistration
from app.modules.auth.service import DB, address_key, limit, provider
from app.modules.tenants.models import Installation

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


async def registration_slot(db: DB) -> Installation:
    install = await db.scalar(
        select(Installation)
        .where(Installation.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    if install.tenant_id or install.subject:
        raise HTTPException(409, "管理员账号已创建，请前往登录")
    return install


@router.post("/register", response_model=Message)
async def register(payload: SetupRegistration, request: Request, db: DB, _: Mutation) -> Message:
    await limit(db, address_key(request, "setup-register"), 10, 300)
    settings = provider(request).settings
    if (
        settings.platform_edition == "community"
        and (not payload.organization_name or len(payload.organization_name.strip()) < 2)
    ) or not payload.name.strip():
        raise HTTPException(422, "请填写组织名称和管理员姓名")
    install = await registration_slot(db)
    if not install.registration_marker:
        # Persist before remote I/O so a retry can recover a created Keycloak user.
        # This is an internal correlation marker, never a user-facing credential.
        install.registration_marker = secrets.token_hex(32)
        await db.commit()
        install = await registration_slot(db)
    assert install.registration_marker is not None
    subject = await provider(request).create_initial_user(
        str(payload.email).casefold(),
        payload.name.strip(),
        payload.password.get_secret_value(),
        install.registration_marker,
    )
    install.issuer = provider(request).settings.oidc_issuer
    install.subject = subject
    install.organization_name = (
        payload.organization_name.strip() if payload.organization_name else None
    )
    await db.commit()
    return Message(message="管理员账号已创建，请登录")
