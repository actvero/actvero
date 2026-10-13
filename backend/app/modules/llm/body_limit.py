"""Bound inference JSON before FastAPI parses it, including chunked request bodies."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute


class InferenceRoute(APIRoute):
    max_bytes = 2_000_000

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def limited(request: Request) -> Response:
            if request.method == "POST":
                if request.headers.get("content-encoding", "identity").lower() != "identity":
                    raise HTTPException(415, "不接受压缩请求体")
                content = bytearray()
                async for chunk in request.stream():
                    content.extend(chunk)
                    if len(content) > self.max_bytes:
                        raise HTTPException(413, f"请求体超过 {self.max_bytes / 1_000_000:g} MB")
                # Starlette body/json readers share this cache after stream consumption.
                request._body = bytes(content)
            return await original(request)

        return limited


class AudioUploadRoute(InferenceRoute):
    max_bytes = 8_100_000
