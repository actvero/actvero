"""One public presentation snapshot; no tenant, operator, SMTP or identity secrets."""

import base64
import binascii
import warnings
from io import BytesIO
from uuid import UUID

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError

from app.modules.platform.brand_schemas import BrandSlot, PublicBranding
from app.modules.tenants.models import Installation

DEFAULT_PLATFORM_NAME = "Actvero"
DEFAULT_REVISION = UUID(int=0)
SLOTS: tuple[BrandSlot, ...] = (
    "mark_light",
    "mark_dark",
    "wordmark_light",
    "wordmark_dark",
    "favicon",
)


def asset_url(app_url: str, asset_id: str | UUID, variant: str = "image.png") -> str:
    return f"{app_url}/api/v1/platform/branding/assets/{asset_id}/{variant}"


def asset_ids(install: Installation) -> dict[BrandSlot, UUID]:
    values = dict(install.branding_assets or {})
    if (
        not values.get("mark_light")
        and install.platform_logo_data
        and install.platform_logo_version
    ):
        values["mark_light"] = str(install.platform_logo_version)
    return {slot: UUID(value) for slot, value in values.items() if slot in SLOTS}


def public_branding(app_url: str, install: Installation | None) -> PublicBranding:
    ids = asset_ids(install) if install else {}
    favicon = ids.get("favicon") or ids.get("mark_light")
    return PublicBranding(
        name=(install.platform_name if install else None) or DEFAULT_PLATFORM_NAME,
        revision=install.branding_revision if install else DEFAULT_REVISION,
        asset_ids=ids,
        assets={slot: asset_url(app_url, value) for slot, value in ids.items()},
        favicon_url=asset_url(app_url, favicon, "favicon.ico")
        if favicon
        else f"{app_url}/favicon.ico",
        apple_icon_url=asset_url(app_url, favicon, "apple.png")
        if favicon
        else f"{app_url}/brand/actvero-icon.png",
    )


def logo_url(app_url: str, install: Installation) -> str | None:
    mark = asset_ids(install).get("mark_light")
    return f"{app_url}/api/v1/platform/logo?v={mark}" if mark else None


def normalize_brand_image(content: str) -> bytes:
    try:
        data = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "图片编码无效，请重新选择") from None
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(413, "每张品牌图片不能超过 2 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise HTTPException(422, "请选择静态 PNG、JPG 或 WebP 图片")
                if source.width * source.height > 16_000_000 or getattr(source, "n_frames", 1) != 1:
                    raise HTTPException(422, "请选择不超过 1600 万像素的静态图片")
                source.load()
                image = ImageOps.exif_transpose(source).convert("RGBA")
                image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
                image.info.clear()
                output = BytesIO()
                image.save(output, format="PNG")
                if output.tell() > 8 * 1024 * 1024:
                    raise HTTPException(413, "解码后的图片过大，请压缩后重试")
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(422, "图片无法读取，请选择有效图片") from None


def render_asset(data: bytes, variant: str) -> tuple[bytes, str]:
    with Image.open(BytesIO(data)) as source:
        image = source.convert("RGBA")
        output = BytesIO()
        if variant == "image.png":
            image.save(output, format="PNG")
            return output.getvalue(), "image/png"
        if variant == "legacy.webp":
            image.save(output, format="WEBP", lossless=True)
            return output.getvalue(), "image/webp"
        sizes = {"favicon.ico": 64, "icon-16.png": 16, "icon-32.png": 32, "apple.png": 180}
        if variant not in sizes:
            raise HTTPException(404, "图片规格不存在")
        size = sizes[variant]
        contained = ImageOps.contain(image, (size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size))
        canvas.alpha_composite(
            contained, ((size - contained.width) // 2, (size - contained.height) // 2)
        )
        if variant == "favicon.ico":
            canvas.save(output, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
            return output.getvalue(), "image/x-icon"
        canvas.save(output, format="PNG")
        return output.getvalue(), "image/png"
