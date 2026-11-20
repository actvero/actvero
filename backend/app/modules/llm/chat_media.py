"""Chat image transport metadata and validation of inline data URLs."""

import base64
import re

from pydantic import BaseModel, Field


class ChatImageInput(BaseModel):
    """An explicit image policy advertised by a route, if available."""

    max_image_bytes: int = Field(ge=1)
    max_total_bytes: int = Field(ge=1)
    max_images: int = Field(ge=1)
    target_pixels: int = Field(ge=1)


_BASE64 = re.compile(r"[A-Za-z0-9+/]+={0,2}")


def validate_image_url(url: str) -> None:
    if url.startswith("https://"):
        return
    comma = url.find(",")
    if comma < 0 or not url.startswith("data:image/") or not url.endswith(";base64", 0, comma):
        raise ValueError("图片须为 HTTPS 地址或 base64 image data URL")
    start = comma + 1
    if (len(url) - start) % 4 or not _BASE64.fullmatch(url, start):
        raise ValueError("图片 base64 编码无效")
    # Only the final quartet can contain padding bits. Validate them without copying the image.
    final = url[-4:]
    if base64.b64encode(base64.b64decode(final, validate=True)).decode("ascii") != final:
        raise ValueError("图片须为规范的 base64 编码")
