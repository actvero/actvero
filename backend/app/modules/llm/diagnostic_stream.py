"""SSE framing around the existing one-attempt Chat SDK stream."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any

import anyio
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.modules.auth.service import now, provider
from app.modules.llm.channel_testing import (
    DiagnosticAdmission,
    audit_result,
    finish_diagnostic,
    persist_result,
)
from app.modules.llm.providers import chat, retrieval, sdk_runtime
from app.modules.llm.router import administrator, channel
from app.modules.llm.schemas import ChannelChatProbe, ChannelTestView


def frame(event: str, data: dict[str, Any]) -> bytes:
    return (
        "event: "
        + event
        + "\ndata: "
        + json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        + "\n\n"
    ).encode()


class DeltaRedactor:
    """Delay possible key prefixes across provider chunks, one string field at a time."""

    def __init__(self, key: str | None) -> None:
        self.key = key
        self.pending: dict[tuple[str, ...], str] = {}

    def take(self, path: tuple[str, ...], value: str) -> str:
        if not self.key:
            return value
        combined = self.pending.get(path, "") + value
        # Consume complete matches first. If a key has a self-overlapping
        # prefix (for example "aaa"), holding a suffix before replacement
        # would emit one character of the complete secret.
        # Channel keys are printable ASCII. Keep the replacement entirely
        # non-ASCII so it cannot itself contain a one-character key or form a
        # new key across the replacement boundary.
        safe = combined.replace(self.key, "〈已隐藏密钥〉")
        tail = next(
            (
                length
                for length in range(min(len(self.key) - 1, len(safe)), 0, -1)
                if safe.endswith(self.key[:length])
            ),
            0,
        )
        self.pending[path] = safe[-tail:] if tail else ""
        return safe[:-tail] if tail else safe

    def delta(self, value: dict[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for name in ("content", "reasoning_content", "refusal"):
            if isinstance(value.get(name), str):
                part = self.take((name,), value[name])
                if part:
                    safe[name] = part
        calls = []
        for item in value.get("tool_calls") or []:
            index = item["index"]
            clean: dict[str, Any] = {"index": index}
            for name in ("id",):
                if isinstance(item.get(name), str):
                    part = self.take(("tool", str(index), name), item[name])
                    if part:
                        clean[name] = part
            if "type" in item:
                clean["type"] = item["type"]
            function = item.get("function") or {}
            fields = {}
            for name in ("name", "arguments"):
                if isinstance(function.get(name), str):
                    part = self.take(("tool", str(index), name), function[name])
                    if part:
                        fields[name] = part
            if fields:
                clean["function"] = fields
            if len(clean) > 1:
                calls.append(clean)
        if calls:
            safe["tool_calls"] = calls
        return safe

    def flush(self) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        tools: dict[int, dict[str, Any]] = {}
        for path, held in self.pending.items():
            if not held:
                continue
            if len(path) == 1:
                safe[path[0]] = held
            elif len(path) == 3:
                index = int(path[1])
                tool = tools.setdefault(index, {"index": index})
                if path[2] == "id":
                    tool["id"] = held
                else:
                    tool.setdefault("function", {})[path[2]] = held
        if tools:
            safe["tool_calls"] = list(tools.values())
        self.pending.clear()
        return safe


def string_size(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(string_size(item) for item in value)
    if isinstance(value, dict):
        return sum(string_size(item) for item in value.values())
    return 0


async def current(request: Request, admitted: DiagnosticAdmission) -> None:
    """A short independent transaction; never hold a lock across SDK I/O/yield."""
    async with request.app.state.database.sessions() as db:
        actor = await administrator(request, db, write=True)
        row = await channel(db, actor, admitted.channel_id)
        if row.version != admitted.channel_version or row.archived:
            raise HTTPException(409, "测试期间渠道已修改，请按请求号核对")


def error_event(exc: BaseException, admitted: DiagnosticAdmission) -> bytes:
    status = exc.status_code if isinstance(exc, HTTPException) else 502
    code = getattr(exc, "code", None)
    code = (
        code
        if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code)
        else "stream_interrupted"
    )
    message = (
        "登录状态已失效，请重新登录后按请求号核对"
        if status == 401
        else "管理员权限已变化，请按请求号核对"
        if status == 403
        else "渠道配置已变化，请按请求号核对"
        if status == 409
        else "上游限流，请按请求号核对"
        if status == 429
        else "流式诊断已中断，请按请求号核对"
    )
    return frame(
        "error",
        {
            "request_id": str(admitted.request_id),
            "status_code": status,
            "error_code": code,
            "message": message,
            "uncertain": admitted.trace.snapshot()["uncertain"],
        },
    )


class StreamLifetime:
    def __init__(self, request: Request, admitted: DiagnosticAdmission) -> None:
        self.request, self.admitted = request, admitted
        self.finalized = False

    async def cancel(self) -> None:
        if self.finalized:
            return
        with anyio.move_on_after(3, shield=True) as scope:
            await finish_diagnostic(
                self.request,
                self.admitted.tenant_id,
                self.admitted.request_id,
                self.admitted.trace,
                None,
                cancelled=True,
                lease=self.admitted.lease,
            )
        if not scope.cancel_called:
            self.finalized = True

    async def fail(self, exc: BaseException, state: chat.StreamState, started: float) -> None:
        if self.finalized:
            return
        trace = self.admitted.trace
        known_rejection = (
            isinstance(exc, retrieval.UpstreamFailure)
            and not exc.uncertain
            and trace.upstream_terminal
        )
        with anyio.move_on_after(3, shield=True) as scope:
            if known_rejection:
                result = ChannelTestView(
                    stream=True,
                    operation="chat",
                    ok=False,
                    message="流式诊断失败",
                    request_id=self.admitted.request_id,
                    tested_at=now(),
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error_code=exc.code if isinstance(exc, retrieval.UpstreamFailure) else None,
                    uncertain=False,
                )
                await persist_result(self.request, self.admitted, result)
            else:
                await finish_diagnostic(
                    self.request,
                    self.admitted.tenant_id,
                    self.admitted.request_id,
                    trace,
                    None,
                    error=exc,
                    lease=self.admitted.lease,
                )
        if not scope.cancel_called:
            self.finalized = True


class DiagnosticStreamingResponse(StreamingResponse):
    """Close a pending receipt even if ASGI fails before first iterator pull."""

    def __init__(self, content: AsyncIterator[bytes], lifetime: StreamLifetime) -> None:
        super().__init__(
            content,
            media_type="text/event-stream",
            headers={"cache-control": "no-store", "x-accel-buffering": "no"},
        )
        self.lifetime = lifetime

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            try:
                with anyio.move_on_after(1, shield=True):
                    close = getattr(self.body_iterator, "aclose", None)
                    if close is not None:
                        await close()
            finally:
                # Iterator close may itself fail or block. Preserve a separate
                # cleanup window for the receipt that admission committed.
                with anyio.move_on_after(4, shield=True):
                    await self.lifetime.cancel()


def stream_response(
    request: Request, admitted: DiagnosticAdmission, body: ChannelChatProbe
) -> StreamingResponse:
    lifetime = StreamLifetime(request, admitted)

    async def events() -> AsyncIterator[bytes]:
        started = time.monotonic()
        state = chat.StreamState()
        redactor = DeltaRedactor(admitted.key)
        text = ""
        delivered_chars = 0
        try:
            yield frame(
                "accepted",
                {
                    "request_id": str(admitted.request_id),
                    "attempt_id": admitted.trace.attempt_id,
                    "operation": "chat",
                    "channel_version": admitted.channel_version,
                },
            )
            await current(request, admitted)
            payload = {
                "model": body.id,
                "messages": [{"role": "user", "content": body.prompt}],
                "max_tokens": body.max_output_tokens,
                "stream": True,
                "stream_options": {"include_usage": True},
            }
            async with aclosing(
                sdk_runtime.events(
                    admitted.adapter,
                    admitted.base,
                    admitted.key,
                    admitted.timeout,
                    provider(request).settings,
                    payload,
                    body.id,
                    str(admitted.request_id),
                    state,
                    target=admitted.target,
                    trace=admitted.trace,
                )
            ) as chunks:
                async for chunk in chunks:
                    delta = chunk["choices"][0]["delta"]
                    emitted = {
                        name: delta[name]
                        for name in ("content", "reasoning_content", "refusal", "tool_calls")
                        if delta.get(name)
                    }
                    if not emitted:
                        continue
                    await current(request, admitted)
                    emitted = redactor.delta(emitted)
                    if not emitted:
                        continue
                    delivered_chars += string_size(emitted)
                    if delivered_chars > 16000:
                        raise retrieval.UpstreamFailure(
                            502,
                            "diagnostic_output_limit",
                            "流式诊断输出超过预览上限",
                            uncertain=True,
                        )
                    if isinstance(emitted.get("content"), str):
                        text += emitted["content"]
                    yield frame("delta", {"request_id": str(admitted.request_id), "delta": emitted})
            await current(request, admitted)
            held = redactor.flush()
            if held:
                delivered_chars += string_size(held)
                if delivered_chars > 16000:
                    raise retrieval.UpstreamFailure(
                        502,
                        "diagnostic_output_limit",
                        "流式诊断输出超过预览上限",
                        uncertain=True,
                    )
                if isinstance(held.get("content"), str):
                    text += held["content"]
                yield frame("delta", {"request_id": str(admitted.request_id), "delta": held})
            usage = state.usage
            original = usage.get("source") == "upstream"
            result = ChannelTestView(
                stream=True,
                operation="chat",
                ok=admitted.trace.upstream_terminal,
                uncertain=not admitted.trace.upstream_terminal,
                message=(
                    "流式对话测试成功"
                    if admitted.trace.upstream_terminal
                    else "对话已结束，上游是否完整执行仍待确认"
                ),
                request_id=admitted.request_id,
                tested_at=now(),
                duration_ms=int((time.monotonic() - started) * 1000),
                output=text,
                usage_source="upstream" if original else "unknown",
                input_tokens=usage.get("input_tokens") if original else None,
                output_tokens=usage.get("output_tokens") if original else None,
            )
            await persist_result(request, admitted, result)
            lifetime.finalized = True
            async with request.app.state.database.sessions() as db:
                await audit_result(request, db, admitted, result)
            await current(request, admitted)
            yield frame(
                "usage",
                {
                    "request_id": str(admitted.request_id),
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "usage_source": result.usage_source,
                    "attempt": result.attempt,
                },
            )
            await current(request, admitted)
            yield frame(
                "result",
                {
                    "request_id": str(admitted.request_id),
                    "status": "unconfirmed" if result.uncertain else "success",
                    "result": result.model_dump(mode="json"),
                },
            )
        except (asyncio.CancelledError, GeneratorExit):
            await lifetime.cancel()
            raise
        except Exception as exc:
            await lifetime.fail(exc, state, started)
            # A late permission/version change overrides an upstream error;
            # never leak the old channel's result or its original exception.
            try:
                await current(request, admitted)
            except HTTPException as changed:
                exc = changed
            yield error_event(exc, admitted)

    return DiagnosticStreamingResponse(events(), lifetime)
