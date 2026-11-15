"""Bound inference JSON before FastAPI parses it, including chunked request bodies."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.routing import APIRoute

INFERENCE_MAX_BODY_MIB = 128


class InferenceRoute(APIRoute):
    max_bytes = INFERENCE_MAX_BODY_MIB * 1024**2
    limit_label = f"{INFERENCE_MAX_BODY_MIB} MiB"

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def limited(request: Request) -> Response:
            if request.method == "POST":
                if request.headers.get("content-encoding", "identity").lower() != "identity":
                    raise HTTPException(415, "不接受压缩请求体")
                content = bytearray()
                async for chunk in request.stream():
                    if len(content) + len(chunk) > self.max_bytes:
                        raise HTTPException(413, f"请求体超过 {self.limit_label}")
                    content.extend(chunk)
                # Starlette body/json readers share this cache after stream consumption.
                request._body = bytes(content)
            return await original(request)

        return limited


class AudioUploadRoute(InferenceRoute):
    max_bytes = 8_100_000
    limit_label = "8.1 MB"
