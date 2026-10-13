"""Atomic brand publication and immutable public derivatives."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse, Response

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, limit, provider
from app.modules.platform.access import platform_access
from app.modules.platform.brand_schemas import (
    BrandImageUpload,
    BrandingSettings,
    BrandingUpdate,
    PublicBranding,
)
from app.modules.platform.branding import (
    asset_ids,
    normalize_brand_image,
    public_branding,
    render_asset,
)
from app.modules.tenants.models import BrandAsset, Installation

router = APIRouter(prefix="/api/v1/platform/branding", tags=["platform"])


def settings_view(request: Request, install: Installation) -> BrandingSettings:
    return BrandingSettings(
        **public_branding(provider(request).settings.app_url, install).model_dump(),
        identity_status="applied"
        if install.identity_branding_revision == install.branding_revision
        else "pending",
    )


@router.get("", response_model=PublicBranding)
async def public_brand(request: Request, response: Response, db: DB) -> PublicBranding:
    value = public_branding(provider(request).settings.app_url, await db.get(Installation, 1))
    request.app.state.brand_snapshot = value
    response.headers["Cache-Control"] = "no-cache"
    response.headers["ETag"] = f'"{value.revision}"'
    return value


@router.get("/settings", response_model=BrandingSettings)
async def brand_settings(request: Request, response: Response, db: DB) -> BrandingSettings:
    await platform_access(request, db)
    install = await db.get(Installation, 1)
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    response.headers["Cache-Control"] = "no-store"
    return settings_view(request, install)


@router.put("/settings", response_model=BrandingSettings)
async def publish_brand(
    payload: BrandingUpdate, request: Request, response: Response, db: DB, _: Mutation
) -> BrandingSettings:
    actor = await platform_access(request, db)
    await limit(db, "brand-publish:" + str(actor.user.id), 20, 60)
    # Decode before taking the publication lock; every image must pass before mutation.
    prepared = {}
    for slot, value in payload.assets.items():
        if isinstance(value, BrandImageUpload):
            prepared[slot] = await run_in_threadpool(normalize_brand_image, value.content)
    await platform_access(request, db)
    install = await db.scalar(
        select(Installation)
        .where(Installation.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if install is None:
        raise HTTPException(503, "数据库尚未完成迁移")
    if install.branding_revision != payload.revision:
        raise HTTPException(409, "品牌已由其他管理员更新，请重新载入后再保存")
    ids = asset_ids(install)
    for slot, value in payload.assets.items():
        if value is None:
            ids.pop(slot, None)
        elif isinstance(value, UUID):
            # Existing assets may only be retained in their current slot. Guessing a
            # public/historical UUID cannot silently resurrect an unrelated image.
            if ids.get(slot) != value:
                raise HTTPException(409, "品牌素材已变化，请重新载入")
        else:
            image = BrandAsset(id=uuid4(), data=prepared[slot], media_type="image/png")
            db.add(image)
            ids[slot] = image.id
    for kind in ("mark", "wordmark"):
        if f"{kind}_dark" in ids and f"{kind}_light" not in ids:
            raise HTTPException(422, "深色背景版本需要同时保留同用途的浅色背景版本")
    install.platform_name = payload.platform_name
    install.branding_assets = {slot: str(value) for slot, value in ids.items()}
    install.branding_revision = uuid4()
    # Deprecated storage is no longer the active source; assets keep old URLs alive.
    if install.platform_logo_data and install.platform_logo_version:
        if await db.get(BrandAsset, install.platform_logo_version) is None:
            db.add(
                BrandAsset(
                    id=install.platform_logo_version,
                    data=install.platform_logo_data,
                    media_type="image/webp",
                )
            )
    install.platform_logo_data = None
    install.platform_logo_version = None
    install.platform_logo_url = None
    await db.commit()
    request.app.state.brand_snapshot = public_branding(provider(request).settings.app_url, install)
    response.headers["Cache-Control"] = "no-store"
    return settings_view(request, install)


@router.get("/assets/{asset_id}/{variant}", response_class=Response)
async def brand_asset(asset_id: UUID, variant: str, request: Request, db: DB) -> Response:
    asset = await db.get(BrandAsset, asset_id)
    if asset is None:
        raise HTTPException(404, "品牌图片不存在")
    if variant not in {"image.png", "favicon.ico", "icon-16.png", "icon-32.png", "apple.png"}:
        raise HTTPException(404, "图片规格不存在")
    headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "ETag": f'"{asset_id}-{variant}"',
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("if-none-match") == headers["ETag"]:
        return Response(status_code=304, headers=headers)
    content, media = await run_in_threadpool(render_asset, asset.data, variant)
    return Response(content, media_type=media, headers=headers)


@router.get("/email-logo.png", response_class=Response)
async def email_logo(request: Request, db: DB) -> Response:
    install = await db.get(Installation, 1)
    ids = asset_ids(install) if install else {}
    chosen = ids.get("wordmark_light") or ids.get("mark_light")
    asset = await db.get(BrandAsset, chosen) if chosen else None
    if asset:
        content, media = await run_in_threadpool(render_asset, asset.data, "image.png")
        return Response(content, media_type=media, headers={"Cache-Control": "no-cache"})
    return FileResponse(
        provider(request).settings.static_dir / "brand/actvero-icon.png",
        headers={"Cache-Control": "no-cache"},
    )
