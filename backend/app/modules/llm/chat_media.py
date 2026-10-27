"""Shared inline-image transport limits for catalog discovery and chat admission."""

import base64
import binascii

from pydantic import BaseModel, Field


class ChatImageInput(BaseModel):
    """Platform transport bounds, independent of supplier model capacities."""

    max_image_bytes: int = Field(default=1024 * 1024, ge=1)
    max_total_bytes: int = Field(default=8 * 1024 * 1024, ge=1)
    max_images: int = Field(default=32, ge=1)
    target_pixels: int = Field(default=2048 * 2048, ge=1)


IMAGE_INPUT = ChatImageInput()
IMAGE_URL_MAX_LENGTH = 1_500_000


def inline_image_bytes(url: str) -> int:
    """Validate bounded inline base64; HTTPS content remains supplier-resolved."""
    if url.startswith("https://"):
        return 0
    header, separator, encoded = url.partition(",")
    if not separator or not header.startswith("data:image/") or not header.endswith(";base64"):
        raise ValueError("图片须为 HTTPS 地址或 base64 image data URL")
    if len(encoded) > 4 * ((IMAGE_INPUT.max_image_bytes + 2) // 3):
        raise ValueError("单张请求图片不能超过 1 MiB，请压缩后重试")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("图片 base64 编码无效") from error
    if not data or base64.b64encode(data).decode("ascii") != encoded:
        raise ValueError("图片须为非空、规范的 base64 编码")
    if len(data) > IMAGE_INPUT.max_image_bytes:
        raise ValueError("单张请求图片不能超过 1 MiB，请压缩后重试")
    return len(data)
