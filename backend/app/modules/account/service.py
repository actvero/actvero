import warnings
from io import BytesIO

from fastapi import HTTPException, Request
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import authenticate, provider
from app.modules.members.service import Access, access
from app.modules.tenants.models import Installation

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_PIXELS = 16_000_000


async def own_access(request: Request, db: AsyncSession, *, write: bool = False) -> Access:
    session, _, _ = await authenticate(request, db)
    tenant_id = session.tenant_id
    install = await db.get(Installation, 1)
    if tenant_id is None and provider(request).settings.platform_edition == "community":
        tenant_id = install.tenant_id if install else None
    if tenant_id is None:
        raise HTTPException(403, "请先加入组织")
    return await access(request, db, tenant_id, admin=False, write=write)


def normalize_avatar(data: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP"}:
                    raise HTTPException(422, "请选择 PNG、JPG 或 WebP 图片")
                if source.width * source.height > MAX_AVATAR_PIXELS:
                    raise HTTPException(422, "图片分辨率过大，请使用不超过 1600 万像素的图片")
                if getattr(source, "n_frames", 1) != 1:
                    raise HTTPException(422, "头像暂不支持动态图，请选择静态图片")
                source.load()
                image = ImageOps.fit(ImageOps.exif_transpose(source).convert("RGBA"), (256, 256))
                image.info.clear()
                output = BytesIO()
                image.save(output, format="WEBP", quality=85)
                return output.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(422, "图片无法读取，请选择有效的 PNG、JPG 或 WebP 图片") from None
