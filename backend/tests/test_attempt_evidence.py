"""Single-attempt evidence uses only local mock transports and synthetic meters."""

import httpx
import httpx2
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.outbound import PinnedTransport
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.providers.sdk_transport import RuntimeTransport


def test_trace_classifies_fields_and_allows_outer_late_finish() -> None:
    trace = AttemptTrace("attempt-1")
    assert trace.snapshot()["sent"] is None
    assert trace.snapshot()["certainly_unused"] is False
    trace.mark_sent()
    trace.observe_usage(
        {
            "source": "upstream",
            "input_tokens": 9,
            "output_tokens": None,
            "input_characters": 22,
            "image_count": 1,
            "private": "never-persist",
        },
    )
    trace.finish(RuntimeError("private-url-and-secret"))
    trace.mark_output()
    trace.mark_upstream_terminal()
    final = trace.finish()
    evidence = {item["field"]: item for item in final["usage_evidence"]}
    assert final["error_code"] == "unexpected_error"
    assert final["output_started"] is True
    assert final["uncertain"] is False
    assert evidence["input_tokens"]["source"] == "upstream"
    assert evidence["output_tokens"]["value"] is None
    assert evidence["output_tokens"]["complete"] is False
    assert evidence["input_characters"]["source"] == "validated_input"
    assert evidence["image_count"]["source"] == "confirmed_delivery"
    assert "private" not in str(final)
    assert "private-url-and-secret" not in str(final)


@pytest.mark.asyncio
async def test_pinned_send_callback_after_validation_only() -> None:
    sent = []

    async def resolver(_: str) -> str:
        return "127.0.0.1"

    transport = PinnedTransport(
        "https://allowed.example/v1", resolver, on_send=lambda: sent.append(1)
    )
    transport.inner = httpx2.MockTransport(lambda _: httpx2.Response(200, json={"ok": True}))
    with pytest.raises(HTTPException):
        await transport.handle_async_request(httpx2.Request("POST", "https://other.example/v1/x"))
    assert sent == []
    response = await transport.handle_async_request(
        httpx2.Request("POST", "https://allowed.example/v1/x")
    )
    assert response.status_code == 200
    assert sent == [1]
    await transport.aclose()


@pytest.mark.asyncio
async def test_runtime_dispatch_and_raw_usage_are_separate_from_client_delivery() -> None:
    base = "http://127.0.0.1:9999/v1"
    trace = AttemptTrace("attempt-2")
    settings = Settings(_env_file=None, llm_allowed_private_origins=[base])
    transport = RuntimeTransport(base, "fake", settings, "openai", trace=trace)
    calls = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        calls.append((request.method, str(request.url)))
        return httpx2.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    transport.inner.inner = httpx2.MockTransport(respond)
    response = await transport.handle_async_request(
        httpx.Request("POST", f"{base}/chat/completions", json={"model": "x"})
    )
    assert response.status_code == 200
    assert len(calls) == 1
    snap = trace.snapshot()
    assert snap["sent"] is True
    assert snap["upstream_terminal"] is True
    assert snap["client_terminal"] is None
    assert snap["output_started"] is False
    assert {(e["field"], e["value"]) for e in snap["usage_evidence"]} >= {
        ("input_tokens", 7),
        ("output_tokens", 3),
    }
    with pytest.raises(HTTPException):
        await transport.handle_async_request(httpx.Request("POST", f"{base}/chat/completions"))
    assert len(calls) == 1
    await transport.aclose()


@pytest.mark.asyncio
async def test_runtime_preflight_rejection_is_certainly_unsent() -> None:
    base = "http://127.0.0.1:9999/v1"
    trace = AttemptTrace("attempt-3")
    settings = Settings(_env_file=None, llm_allowed_private_origins=[base])
    transport = RuntimeTransport(base, "fake", settings, "openai", trace=trace)
    transport.inner.inner = httpx2.MockTransport(lambda _: pytest.fail("dispatch must not occur"))
    with pytest.raises(HTTPException):
        await transport.handle_async_request(
            httpx.Request("POST", "https://wrong.example/chat/completions")
        )
    snap = trace.finish()
    assert snap["sent"] is False
    assert snap["certainly_unused"] is True
    assert snap["uncertain"] is False
    assert snap["error_scope"] == "preflight"
    await transport.aclose()


@pytest.mark.asyncio
async def test_stream_partial_meter_is_not_completed_without_done() -> None:
    base = "http://127.0.0.1:9999/v1"
    trace = AttemptTrace("attempt-4")
    settings = Settings(_env_file=None, llm_allowed_private_origins=[base])
    transport = RuntimeTransport(base, "fake", settings, "openai", trace=trace)
    chunks = (
        b'data: {"choices":[{"delta":{"content":"hello"}}],'
        b'"usage":{"prompt_tokens":6,"completion_tokens":2}}\n\n'
    )
    transport.inner.inner = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=httpx2.ByteStream(chunks)
        )
    )
    response = await transport.handle_async_request(
        httpx.Request("POST", f"{base}/chat/completions")
    )
    assert b"hello" in b"".join([chunk async for chunk in response.aiter_raw()])
    snap = trace.finish(cancelled=True)
    assert snap["sent"] is True
    assert snap["upstream_terminal"] is False
    assert snap["uncertain"] is True
    evidence = {item["field"]: item for item in snap["usage_evidence"]}
    assert evidence["raw_prompt_tokens"]["value"] == 6
    assert evidence["raw_prompt_tokens"]["complete"] is False
    assert evidence["input_tokens"]["phase"] == "partial"
    await transport.aclose()


@pytest.mark.asyncio
async def test_missing_upstream_usage_is_not_zero_evidence() -> None:
    base = "http://127.0.0.1:9999/v1"
    trace = AttemptTrace("attempt-5")
    settings = Settings(_env_file=None, llm_allowed_private_origins=[base])
    transport = RuntimeTransport(base, "fake", settings, "openai", trace=trace)
    transport.inner.inner = httpx2.MockTransport(
        lambda _: httpx2.Response(200, json={"choices": [{"finish_reason": "stop"}]})
    )
    await transport.handle_async_request(httpx.Request("POST", f"{base}/chat/completions"))
    snap = trace.finish()
    assert snap["sent"] is True
    assert snap["upstream_terminal"] is True
    assert snap["usage_evidence"] == []
    await transport.aclose()


@pytest.mark.asyncio
async def test_upstream_429_is_explicit_failed_terminal_but_not_unused() -> None:
    base = "http://127.0.0.1:9999/v1"
    trace = AttemptTrace("attempt-6")
    settings = Settings(_env_file=None, llm_allowed_private_origins=[base])
    transport = RuntimeTransport(base, "fake", settings, "openai", trace=trace)
    transport.inner.inner = httpx2.MockTransport(
        lambda _: httpx2.Response(429, headers={"retry-after": "1"})
    )
    with pytest.raises(HTTPException):
        await transport.handle_async_request(httpx.Request("POST", f"{base}/chat/completions"))
    snap = trace.finish()
    assert snap["sent"] is True
    assert snap["upstream_terminal"] is True
    assert snap["upstream_status"] == 429
    assert snap["error_code"] == "upstream_rate_limited"
    assert snap["uncertain"] is False
    assert snap["certainly_unused"] is False
    await transport.aclose()
