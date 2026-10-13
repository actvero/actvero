"""Deliver bounded raster bytes to the authenticated response; no public asset URLs."""

import asyncio
import base64
from io import BytesIO
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx2
from fastapi import HTTPException
from PIL import Image

from app.core.config import Settings
from app.core.outbound import PinnedTransport, endpoint, resolve
from app.modules.llm.image_schemas import GeneratedImage
from app.modules.llm.providers.retrieval import UpstreamFailure

MAX_IMAGE_BYTES = 8_000_000
MAX_PIXELS = 16_000_000
LiteralMime = Literal["image/png", "image/jpeg", "image/webp"]


def validate_image(content: bytes) -> GeneratedImage:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ValueError("Invalid image size")
    with Image.open(BytesIO(content), formats=["PNG", "JPEG", "WEBP"]) as img:
        width, height = img.size
        if width * height > MAX_PIXELS or getattr(img, "n_frames", 1) != 1:
            raise ValueError("Image exceeds supported pixel/frame limit")
        mime = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[img.format or ""]
        img.verify()
    # verify() does not decode the pixels. A second bounded open catches truncated data.
    with Image.open(BytesIO(content), formats=["PNG", "JPEG", "WEBP"]) as img:
        img.load()
    return GeneratedImage(
        b64_json=base64.b64encode(content).decode("ascii"),
        media_type=cast("LiteralMime", mime),
        width=width,
        height=height,
        bytes=len(content),
    )


async def fetch_image(url: str, settings: Settings) -> bytes:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.fragment
        or len(url) > 8192
        or any(ord(c) < 33 for c in url)
    ):
        raise ValueError("Invalid generated image URL")
    # Signed query parameters are permitted only on this one image fetch.
    endpoint(parts._replace(query="").geturl())
    transport = PinnedTransport(
        url,
        lambda bare: resolve(bare, [], dns=settings.llm_public_dns),
        max_bytes=MAX_IMAGE_BYTES,
    )
    async with asyncio.timeout(10):
        async with httpx2.AsyncClient(
            transport=transport, trust_env=False, follow_redirects=False, timeout=10
        ) as client:
            async with client.stream("GET", url, headers={"accept-encoding": "identity"}) as res:
                if (
                    res.status_code != 200
                    or res.headers.get("content-encoding", "identity").lower() != "identity"
                ):
                    raise ValueError("Image download failed")
                return await res.aread()


async def deliver_image(value: object, settings: Settings) -> GeneratedImage:
    try:
        if not isinstance(value, dict):
            raise ValueError("Invalid image result")
        encoded, url = value.get("b64_json"), value.get("url")
        if bool(encoded) == bool(url):
            raise ValueError("Ambiguous or absent image result")
        if encoded:
            if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
                raise ValueError("Invalid encoded image size")
            content = base64.b64decode(encoded, validate=True)
        elif isinstance(url, str):
            content = await fetch_image(url, settings)
        else:
            raise ValueError("Invalid image location")
        return await asyncio.to_thread(validate_image, content)
    except (
        ValueError,
        OSError,
        KeyError,
        SyntaxError,
        Image.DecompressionBombError,
        HTTPException,
        httpx2.HTTPError,
        TimeoutError,
    ):
        raise UpstreamFailure(
            502,
            "image_delivery_failed",
            "上游已响应，但图片无法安全读取；请先核对上游记录",
            uncertain=True,
            health_failure=False,
            retryable=False,
        ) from None
