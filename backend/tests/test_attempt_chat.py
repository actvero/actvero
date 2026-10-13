"""Chat diagnostic and formal SDK share one request-local attempt boundary."""

from uuid import uuid4

import pytest
from test_mcp import listening
from test_sdk_runtime import MODELS, fixture_provider

from app.core.config import Settings
from app.modules.llm.providers import chat, sdk, sdk_runtime
from app.modules.llm.providers.attempt import AttemptTrace

pytestmark = pytest.mark.asyncio


def setup(adapter: str, url: str) -> tuple[str, Settings]:
    return (
        url + ("/v1" if adapter == "openai" else ""),
        Settings(_env_file=None, llm_allowed_private_origins=[url]),
    )


@pytest.mark.parametrize("adapter", list(MODELS))
async def test_diagnostic_uses_formal_one_send_and_native_raw_counters(adapter: str) -> None:
    upstream, calls = fixture_provider(adapter)
    async with listening(upstream) as url:
        base, settings = setup(adapter, url)
        trace = AttemptTrace()
        result = await sdk.test_chat(
            adapter=adapter,
            base=base,
            key="fake-test-key",
            model=MODELS[adapter],
            prompt="hello",
            max_output=32,
            timeout=5,
            settings=settings,
            request_id=uuid4(),
            trace=trace,
        )
    assert len(calls) == 1
    assert result.ok and result.output == "hello"
    assert result.usage_source == "upstream"
    assert result.input_tokens == (70 if adapter == "anthropic" else 100)
    assert result.output_tokens == 3  # Gemini display excludes separate thoughtsTokenCount.
    evidence = trace.snapshot()
    assert evidence["sent"] is True
    assert evidence["upstream_terminal"] is True
    assert evidence["client_terminal"] is None
    assert any(item["source"] == "upstream" for item in evidence["usage_evidence"])


@pytest.mark.parametrize("adapter", list(MODELS))
async def test_stream_tool_conversion_marks_real_output_and_terminal(adapter: str) -> None:
    upstream, calls = fixture_provider(adapter, tools=True)
    async with listening(upstream) as url:
        base, settings = setup(adapter, url)
        trace = AttemptTrace()
        state = chat.StreamState()
        events = [
            item
            async for item in sdk_runtime.events(
                adapter,
                base,
                "fake-test-key",
                5,
                settings,
                {
                    "model": MODELS[adapter],
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 32,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "lookup",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"q": {"type": "string"}},
                                },
                            },
                        }
                    ],
                },
                "public-model",
                str(uuid4()),
                state,
                trace=trace,
            )
        ]
    assert len(calls) == 1
    if adapter == "openai":
        assert any(
            choice["delta"].get("content") for event in events for choice in event["choices"]
        )
    else:
        assert any(
            choice["delta"].get("tool_calls") for event in events for choice in event["choices"]
        )
    assert state.finished and trace.output_started and trace.upstream_terminal
    assert trace.client_terminal is None


@pytest.mark.parametrize("adapter", list(MODELS))
async def test_truncated_stream_never_marks_upstream_terminal(adapter: str) -> None:
    upstream, calls = fixture_provider(adapter, broken=True)
    async with listening(upstream) as url:
        base, settings = setup(adapter, url)
        trace = AttemptTrace()
        state = chat.StreamState()
        async for _ in sdk_runtime.events(
            adapter,
            base,
            "fake-test-key",
            5,
            settings,
            {
                "model": MODELS[adapter],
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 32,
                "stream": True,
            },
            "public-model",
            str(uuid4()),
            state,
            trace=trace,
        ):
            pass
    assert len(calls) == 1
    assert trace.sent is True and trace.output_started and not trace.upstream_terminal
    assert trace.client_terminal is None


@pytest.mark.parametrize("adapter", list(MODELS))
async def test_missing_raw_usage_does_not_become_free_or_sdk_estimate(adapter: str) -> None:
    upstream, calls = fixture_provider(adapter, metered=False)
    async with listening(upstream) as url:
        base, settings = setup(adapter, url)
        trace = AttemptTrace()
        result = await sdk.test_chat(
            adapter=adapter,
            base=base,
            key="fake-test-key",
            model=MODELS[adapter],
            prompt="hello",
            max_output=32,
            timeout=5,
            settings=settings,
            request_id=uuid4(),
            trace=trace,
        )
    assert len(calls) == 1
    if adapter == "openai":
        assert result.ok
    else:
        assert not result.ok and result.uncertain
    assert result.usage_source == "unknown"
    assert result.input_tokens is None and result.output_tokens is None
    assert not any(item["complete"] for item in trace.snapshot()["usage_evidence"])


@pytest.mark.parametrize(
    "status,code", [(401, "upstream_auth"), (429, "upstream_rate_limit"), (503, "upstream_error")]
)
async def test_diagnostic_error_mapping_is_safe_and_single_send(status: int, code: str) -> None:
    upstream, calls = fixture_provider("openai", status=status)
    async with listening(upstream) as url:
        base, settings = setup("openai", url)
        trace = AttemptTrace()
        result = await sdk.test_chat(
            adapter="openai",
            base=base,
            key="fake-test-key",
            model=MODELS["openai"],
            prompt="hello",
            max_output=32,
            timeout=5,
            settings=settings,
            request_id=uuid4(),
            trace=trace,
        )
    assert len(calls) == 1
    assert not result.ok and result.error_code == code
    assert "private-upstream-secret" not in repr(result)
    assert "fake-test-key" not in repr(result)
    assert "private-upstream-secret" not in repr(trace.snapshot())


async def test_close_stream_marks_cancellation_without_success() -> None:
    upstream, calls = fixture_provider("openai")
    async with listening(upstream) as url:
        base, settings = setup("openai", url)
        trace = AttemptTrace()
        state = chat.StreamState()
        stream = sdk_runtime.events(
            "openai",
            base,
            "fake-test-key",
            5,
            settings,
            {
                "model": MODELS["openai"],
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 32,
                "stream": True,
            },
            "public-model",
            str(uuid4()),
            state,
            trace=trace,
        )
        await anext(stream)
        await stream.aclose()
    evidence = trace.snapshot()
    assert len(calls) == 1
    assert evidence["sent"] is True and evidence["client_terminal"] is None
    assert evidence["error_code"] == "caller_cancelled"
