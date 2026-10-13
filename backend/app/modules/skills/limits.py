from fastapi import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SkillUploadLimit:
    """Bound both Content-Length and chunked imports before JSON allocation."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in {
            "/api/v1/skills/import",
            "/api/v1/skills/preview",
        }:
            await self.app(scope, receive, send)
            return
        size = 0

        async def bounded() -> Message:
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > 28_100_000:
                raise HTTPException(413, "技能包不能超过 20 MB")
            return message

        await self.app(scope, bounded, send)
