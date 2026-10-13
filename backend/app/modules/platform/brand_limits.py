from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BrandUploadLimit:
    """Bound chunked and fixed-size JSON before allocating base64 image payloads."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") != "/api/v1/platform/branding/settings":
            await self.app(scope, receive, send)
            return
        size = 0

        async def bounded() -> Message:
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > 14_100_000:
                raise HTTPException(413, "品牌图片合计不能超过 10 MB")
            return message

        await self.app(scope, bounded, send)
