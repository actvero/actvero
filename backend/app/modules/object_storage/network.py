"""Untrusted download URLs use the shared DNS-pinned transport on every redirect."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urljoin

import httpx2
from fastapi import HTTPException

from app.core.config import Settings
from app.core.outbound import PinnedTransport, origin, resolve
from app.modules.object_storage.validation import https_url


@asynccontextmanager
async def download(
    url: str, settings: Settings, *, byte_range: bool = False
) -> AsyncIterator[httpx2.Response]:
    for _ in range(5):
        https_url(url)
        base = origin(url)

        async def resolver(value: str) -> str:
            return await resolve(value, settings.client_distribution_allowed_private_origins)

        async with httpx2.AsyncClient(
            transport=PinnedTransport(base, resolver, max_bytes=20_000_000_001),
            follow_redirects=False,
            trust_env=False,
            timeout=httpx2.Timeout(45, connect=10),
        ) as client:
            headers = {"Accept-Encoding": "identity"}
            if byte_range:
                headers["Range"] = "bytes=0-0"
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise HTTPException(422, "下载重定向缺少地址")
                    url = urljoin(url, location)
                    continue
                if response.status_code not in {200, 206}:
                    raise HTTPException(422, "下载地址不可用，请检查文件权限和地址有效期")
                if response.headers.get("content-encoding", "identity") != "identity":
                    raise HTTPException(422, "下载服务修改了文件编码，请关闭自动压缩")
                yield response
                return
    raise HTTPException(422, "下载重定向次数过多")


async def check_range(url: str, settings: Settings, size: int) -> bool:
    async with download(url, settings, byte_range=True) as response:
        if (
            response.status_code != 206
            or response.headers.get("content-range") != f"bytes 0-0/{size}"
        ):
            return False
        data = bytearray()
        async for block in response.aiter_bytes():
            data.extend(block)
            if len(data) > 1:
                return False
        return len(data) == 1
