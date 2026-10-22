import json
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import anyio
from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB
from app.modules.desktop.errors import fail
from app.modules.llm import runtime
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.inference_router import admin_router, router
from app.modules.llm.inference_schemas import EmbeddingOutput, RerankOutput
from app.modules.llm.providers.retrieval import UpstreamFailure


@dataclass
class Execution:
    events: AsyncGenerator[EmbeddingOutput | RerankOutput | dict[str, Any]] | None = None


async def execution_lifetime(db: DB) -> AsyncIterator[Execution]:
    # Depending on DB places this cleanup before the request session closes, even
    # if cancellation happens between the prefetched event and response startup.
    holder = Execution()
    try:
        yield holder
    finally:
        if holder.events is not None:
            with anyio.move_on_after(3, shield=True):
                await holder.events.aclose()


ExecutionLife = Annotated[Execution, Depends(execution_lifetime)]


def sse(value: dict[str, Any]) -> bytes:
    return ("data: " + json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n\n").encode()


async def response(
    request: Request,
    db: DB,
    model_id: UUID,
    body: ChatInput,
    lifetime: Execution,
    *,
    test: bool = False,
    specific: tuple[UUID, str] | None = None,
) -> JSONResponse | StreamingResponse:
    events = runtime.execute(request, db, model_id, body, test=test, specific=specific)
    lifetime.events = events
    try:
        first = await anext(
            events
        )  # Admission and pre-first-event errors retain their HTTP status.
    except BaseException:
        await events.aclose()
        raise
    if not body.stream:
        await events.aclose()
        return JSONResponse(first)

    async def stream() -> AsyncIterator[bytes]:
        try:
            assert isinstance(first, dict)
            yield sse(first)
            async for event in events:
                assert isinstance(event, dict)
                yield sse(event)
            yield b"data: [DONE]\n\n"
        except HTTPException as exc:
            yield sse(
                {
                    "error": {
                        "code": getattr(exc, "code", "stream_failed"),
                        "message": str(exc.detail)
                        if isinstance(exc, UpstreamFailure)
                        else "对话流已中断，请查看调用状态后重试",
                    }
                }
            )
        finally:
            with anyio.move_on_after(3, shield=True):
                await events.aclose()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"cache-control": "no-store", "x-accel-buffering": "no"},
    )


@router.post(
    "/chat/completions", response_model=None, summary="OpenAI 兼容对话、工具与 SSE 流式输出"
)
async def completions(
    request: Request, db: DB, body: ChatInput, lifetime: ExecutionLife
) -> JSONResponse | StreamingResponse:
    model_id = await runtime.resolve_model(request, db, body.model)
    return await response(request, db, model_id, body, lifetime)


@admin_router.post(
    "/{model_id}/test/chat", response_model=None, summary="管理员真实对话测试，不占成员额度"
)
async def test_chat(
    model_id: UUID,
    request: Request,
    db: DB,
    body: ChatInput,
    _: Mutation,
    lifetime: ExecutionLife,
    channel_id: UUID | None = None,
    upstream_id: str = Query("", max_length=200),
) -> JSONResponse | StreamingResponse:
    if bool(channel_id) != bool(upstream_id):
        fail(422, "invalid_route", "指定测试须同时提供渠道和上游模型")
    return await response(
        request,
        db,
        model_id,
        body,
        lifetime,
        test=True,
        specific=(channel_id, upstream_id) if channel_id else None,
    )
