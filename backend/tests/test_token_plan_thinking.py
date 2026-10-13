"""Token Plan thinking switch through the pinned LiteLLM SDK and a local upstream."""

import json
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from test_mcp import listening

from app.core.config import Settings
from app.modules.llm.catalog_schemas import CatalogInput, ModelBinding
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.providers import chat, sdk_runtime

pytestmark = pytest.mark.asyncio


def config() -> CatalogInput:
    return CatalogInput.model_validate(
        {
            "slug": "public-model",
            "name": "Public model",
            "max_output": 64,
            "capabilities": {
                "reasoning": "supported",
                "streaming": "supported",
                "tools": "supported",
            },
            "reasoning_options": [
                {"type": "toggle"},
                {"type": "budget_tokens", "min": 1, "max": 32},
                {"type": "effort", "values": ["low", "none"]},
            ],
        }
    )


def binding(reasoning_format: str = "enable_thinking") -> ModelBinding:
    return ModelBinding.model_validate(
        {
            "channel_id": str(uuid4()),
            "upstream_id": "qwen3.8-max",
            "chat_options": {
                "reasoning_format": reasoning_format,
                "output_parameter": "max_tokens",
            },
        }
    )


def request(enabled: bool, *, stream: bool, tools: bool = False) -> ChatInput:
    values: dict = {
        "model": "public-model",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": stream,
        "thinking": {"type": "enabled" if enabled else "disabled"},
    }
    if tools:
        values["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
    return ChatInput.model_validate(values)


def upstream():
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def completion(path: str, incoming: Request):
        body = await incoming.json()
        calls.append((path, dict(incoming.headers), body))
        usage = {"prompt_tokens": 17, "completion_tokens": 5}
        if not body.get("stream"):
            return {
                "id": "local",
                "object": "chat.completion",
                "created": 1,
                "model": body["model"],
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }

        async def events():
            chunks = [
                {
                    "id": "local",
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": "hello"},
                            "finish_reason": None,
                        }
                    ],
                },
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": usage},
            ]
            for chunk in chunks:
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app, calls


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("stream", [False, True])
async def test_explicit_switch_reaches_real_sdk_and_preserves_raw_usage(enabled, stream):
    app, calls = upstream()
    body = request(enabled, stream=stream, tools=True)
    payload = chat.prepare(body, config(), binding(), adapter="openai")
    assert "thinking" not in payload
    assert payload["extra_body"] == {"enable_thinking": enabled}

    async with listening(app) as url:
        base = url + "/compatible-mode/v1"
        settings = Settings(_env_file=None, llm_allowed_private_origins=[url])
        if stream:
            state = chat.StreamState()
            chunks = [
                chunk
                async for chunk in sdk_runtime.events(
                    "openai",
                    base,
                    "local-test-key",
                    10,
                    settings,
                    payload,
                    "public-model",
                    str(uuid4()),
                    state,
                )
            ]
            assert state.finished and state.usage["input_tokens"] == 17
            assert state.usage["output_tokens"] == 5
            assert any(c["choices"][0]["delta"].get("content") == "hello" for c in chunks)
        else:
            raw_usage = {}
            result = await sdk_runtime.complete(
                "openai", base, "local-test-key", 10, settings, payload, meter_raw=raw_usage
            )
            assert raw_usage == {"prompt_tokens": 17, "completion_tokens": 5}
            assert result["usage"]["prompt_tokens"] == 17
            assert result["usage"]["completion_tokens"] == 5

    assert len(calls) == 1
    path, headers, sent = calls[0]
    assert path == "compatible-mode/v1/chat/completions"
    assert headers["authorization"] == "Bearer local-test-key"
    assert sent["model"] == "qwen3.8-max"
    assert sent["enable_thinking"] is enabled
    assert "thinking" not in sent
    assert sent["tools"][0]["function"]["name"] == "lookup"
    assert sent.get("stream", False) is stream
    assert (sent.get("stream_options") == {"include_usage": True}) is stream


@pytest.mark.parametrize(
    "extra",
    [
        {"thinking": {"type": "enabled", "budget_tokens": 8}},
        {"thinking": {"type": "enabled"}, "reasoning_effort": "low"},
        {"reasoning_effort": "low"},
    ],
)
async def test_sdk_receives_requested_options_without_platform_compatibility_guesses(extra):
    body = ChatInput.model_validate(
        {"model": "public-model", "messages": [{"role": "user", "content": "hi"}], **extra}
    )
    prepared = chat.prepare(body, config(), binding(), adapter="openai")
    if "reasoning_effort" in extra:
        assert prepared["reasoning_effort"] == extra["reasoning_effort"]
    if extra.get("thinking", {}).get("budget_tokens"):
        assert prepared["thinking"] == extra["thinking"]
    if "thinking" in extra:
        assert prepared["extra_body"] == {"enable_thinking": True}


async def test_existing_openai_reasoning_dialect_is_unchanged():
    body = request(False, stream=False)
    payload = chat.prepare(body, config(), binding("openai"), adapter="openai")
    assert payload["reasoning_effort"] == "none"
    assert "enable_thinking" not in str(payload)


async def test_toggle_only_model_repairs_legacy_openai_binding():
    toggle_only = CatalogInput.model_validate(
        {**config().model_dump(), "reasoning_options": [{"type": "toggle"}]}
    )
    body = request(True, stream=False)
    payload = chat.prepare(body, toggle_only, binding("openai"), adapter="openai")
    assert payload["extra_body"] == {"enable_thinking": True}
    assert "reasoning_effort" not in payload

    disabled = chat.prepare(
        request(False, stream=False), toggle_only, binding("openai"), adapter="openai"
    )
    assert disabled["extra_body"] == {"enable_thinking": False}


async def test_token_plan_binding_does_not_inject_thinking_without_request():
    body = ChatInput.model_validate(
        {"model": "public-model", "messages": [{"role": "user", "content": "hi"}]}
    )
    payload = chat.prepare(body, config(), binding(), adapter="openai")
    assert "thinking" not in payload and "extra_body" not in payload
