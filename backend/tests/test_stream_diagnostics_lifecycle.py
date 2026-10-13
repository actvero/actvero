"""ASGI failure and late authorization boundaries for diagnostic SSE."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from starlette.requests import ClientDisconnect

from app.modules.llm import diagnostic_stream
from app.modules.llm.channel_testing import DiagnosticAdmission
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.schemas import ChannelChatProbe

pytestmark = pytest.mark.asyncio


def admission() -> DiagnosticAdmission:
    request_id = uuid4()
    return DiagnosticAdmission(
        request_id=request_id,
        tenant_id=uuid4(),
        channel_id=uuid4(),
        channel_version=1,
        metadata={},
        trace=AttemptTrace(str(request_id)),
        lease=None,
        adapter="openai",
        base="https://example.invalid/v1",
        key="fake-key",
        timeout=5,
        target=None,
    )


def request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


async def receive() -> dict:
    await asyncio.sleep(10)
    return {"type": "http.disconnect"}


SCOPE = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"}}


async def test_response_start_send_failure_finishes_pending_without_sdk_dispatch(monkeypatch):
    finished = AsyncMock()
    sdk = AsyncMock()
    monkeypatch.setattr(diagnostic_stream, "finish_diagnostic", finished)
    monkeypatch.setattr(diagnostic_stream.sdk_runtime, "events", sdk)
    body = ChannelChatProbe(
        version=1, id="test-model", operation="chat", prompt="test", max_output_tokens=8
    )
    response = diagnostic_stream.stream_response(request(), admission(), body)

    async def broken_send(_message):
        raise OSError("client socket closed before response started")

    with pytest.raises(ClientDisconnect):
        await response(SCOPE, receive, broken_send)
    finished.assert_awaited_once()
    assert finished.await_args.kwargs["cancelled"] is True
    sdk.assert_not_called()


@pytest.mark.parametrize("close_problem", ["exception", "timeout"])
async def test_iterator_close_problem_never_skips_pending_cleanup(close_problem):
    lifetime = SimpleNamespace(cancel=AsyncMock())

    class BrokenIterator:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return b"unused"

        async def aclose(self):
            if close_problem == "exception":
                raise RuntimeError("iterator close failed")
            await asyncio.sleep(10)

    response = diagnostic_stream.DiagnosticStreamingResponse(BrokenIterator(), lifetime)

    async def broken_send(_message):
        raise OSError("client socket closed")

    with pytest.raises((ClientDisconnect, RuntimeError)):
        await response(SCOPE, receive, broken_send)
    lifetime.cancel.assert_awaited_once()


async def test_revocation_after_usage_prevents_success_result_event(monkeypatch):
    admitted = admission()
    checks = 0

    async def current(_request, _admitted):
        nonlocal checks
        checks += 1
        if checks == 5:
            raise HTTPException(403, "administrator revoked")

    async def events(*args, **kwargs):
        state = args[8]
        state.usage = {"source": "upstream", "input_tokens": 1, "output_tokens": 2}
        yield {"choices": [{"delta": {"content": "validated"}}]}

    async def persist(_request, _admitted, result):
        result.attempt = admitted.trace.snapshot()

    monkeypatch.setattr(diagnostic_stream, "current", current)
    monkeypatch.setattr(
        diagnostic_stream, "provider", lambda _request: SimpleNamespace(settings=object())
    )
    monkeypatch.setattr(diagnostic_stream.sdk_runtime, "events", events)
    monkeypatch.setattr(diagnostic_stream, "persist_result", persist)
    monkeypatch.setattr(diagnostic_stream, "audit_result", AsyncMock())

    @asynccontextmanager
    async def sessions():
        yield object()

    test_request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [],
            "app": SimpleNamespace(
                state=SimpleNamespace(database=SimpleNamespace(sessions=sessions))
            ),
        }
    )
    body = ChannelChatProbe(
        version=1, id="test-model", operation="chat", prompt="test", max_output_tokens=8
    )
    response = diagnostic_stream.stream_response(test_request, admitted, body)
    frames = [part async for part in response.body_iterator]
    assert checks == 6, frames  # Last check precedes the terminal error, too.
    assert any(b"event: usage" in part for part in frames)
    assert any(b"event: error" in part and b'"status_code":403' in part for part in frames)
    assert not any(b"event: result" in part for part in frames)
