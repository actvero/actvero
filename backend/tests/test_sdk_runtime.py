"""Real pinned SDK against loopback providers; no credentials or paid inference."""

import json
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from llm_billing_helpers import billing
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model
from test_llm_channels import create as create_channel
from test_llm_execution import entries, payload
from test_llm_routing import update
from test_mcp import listening

from app.core.config import Settings
from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.providers import chat, sdk_runtime
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk_meter import Meter

pytestmark = pytest.mark.asyncio
env = identity_env
MODELS = {
    "openai": "test-model",
    "anthropic": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.5-flash",
}


def fixture_provider(adapter, *, metered=True, broken=False, status=200, tools=False):
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def call(path: str, request: Request):
        body = await request.json()
        calls.append((path, dict(request.headers), body))
        if status != 200:
            return JSONResponse(
                {"error": {"message": "private-upstream-secret"}}, status_code=status
            )
        if adapter == "anthropic":
            usage = {
                "input_tokens": 70,
                "output_tokens": 3,
                "cache_read_input_tokens": 20,
                "cache_creation_input_tokens": 10,
                "cache_creation": {"ephemeral_5m_input_tokens": 8, "ephemeral_1h_input_tokens": 2},
            }
            content = (
                {"type": "tool_use", "id": "tool_1", "name": "lookup", "input": {"q": "hi"}}
                if tools
                else {"type": "text", "text": "hello"}
            )
            result = {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [content],
                "stop_reason": "tool_use" if tools else "end_turn",
            }
            if metered:
                result["usage"] = usage
            chunks = [
                {
                    "type": "message_start",
                    "message": {
                        **result,
                        "content": [],
                        "stop_reason": None,
                        "usage": {**usage, "output_tokens": 0} if metered else {},
                    },
                },
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {**content, "input": {}}
                    if tools
                    else {"type": "text", "text": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"q":"hi"}'}
                    if tools
                    else {"type": "text_delta", "text": "hello"},
                },
                {"type": "content_block_stop", "index": 0},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": result["stop_reason"]},
                    **({"usage": {"output_tokens": 3}} if metered else {}),
                },
                {"type": "message_stop"},
            ]
        elif adapter == "gemini":
            part = (
                {"functionCall": {"name": "lookup", "args": {"q": "hi"}}}
                if tools
                else {"text": "hello"}
            )
            result = {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [part]},
                        "index": 0,
                        "finishReason": "STOP",
                    }
                ]
            }
            if metered:
                result["usageMetadata"] = {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 3,
                    "thoughtsTokenCount": 2,
                    "cachedContentTokenCount": 20,
                    "totalTokenCount": 105,
                }
            chunks = [result]
        else:
            result = {
                "id": "test",
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
            }
            if metered:
                result["usage"] = {"prompt_tokens": 100, "completion_tokens": 3}
            chunks = [
                {
                    "id": "test",
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
                {"choices": [], **({"usage": result["usage"]} if metered else {})},
            ]
        streaming = body.get("stream") or "streamGenerateContent" in path
        if not streaming:
            return result

        async def events():
            data = chunks
            if broken:
                if adapter == "gemini":
                    data = [
                        {
                            "candidates": [
                                {
                                    "content": {"role": "model", "parts": [{"text": "partial"}]},
                                    "index": 0,
                                }
                            ]
                        }
                    ]
                else:
                    data = chunks[:3] if adapter == "anthropic" else chunks[:1]
            for item in data:
                # Split framing and UTF-8 across transport chunks to exercise the meter observer.
                encoded = ("data: " + json.dumps(item) + "\n\n").encode()
                yield encoded[:11]
                yield encoded[11:]
            if adapter == "openai" and not broken:
                yield b"data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app, calls


async def invoke(adapter, url, *, stream=False, tools=False):
    payload = {
        "model": MODELS[adapter],
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 32,
        "stream": stream,
    }
    if tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            }
        ]
    if stream:
        payload["stream_options"] = {"include_usage": True}
    base = url + ("/v1" if adapter == "openai" else "")
    settings = Settings(_env_file=None, llm_allowed_private_origins=[url])
    if not stream:
        return await sdk_runtime.complete(adapter, base, "test-secret", 10, settings, payload)
    state = chat.StreamState()
    items = [
        item
        async for item in sdk_runtime.events(
            adapter, base, "test-secret", 10, settings, payload, "public-model", str(uuid4()), state
        )
    ]
    return {"choices": items, "usage": state.usage}


@pytest.mark.parametrize("adapter", list(MODELS))
@pytest.mark.parametrize("stream", [False, True])
async def test_real_sdk_protocol_usage_and_one_attempt(adapter, stream):
    app, calls = fixture_provider(adapter)
    async with listening(app) as url:
        result = await invoke(adapter, url, stream=stream)
    assert len(calls) == 1
    path, headers, body = calls[0]
    assert "test-secret" not in str(result)
    usage = result["usage"] if stream else chat.usage(result["usage"])
    assert usage["source"] == "upstream", result
    if adapter == "anthropic":
        assert path == "v1/messages" and headers["x-api-key"] == "test-secret"
        assert (
            usage["input_tokens"],
            usage["output_tokens"],
            usage["cache_read_tokens"],
            usage["cache_write_5m_tokens"],
            usage["cache_write_1h_tokens"],
        ) == (70, 3, 20, 8, 2)
    elif adapter == "gemini":
        assert "generatecontent" in path.lower()
        assert usage["input_tokens"] == 80 and usage["output_tokens"] == 5
    else:
        assert path == "v1/chat/completions"
        assert usage["input_tokens"] == 100 and usage["output_tokens"] == 3


async def test_meter_observation_failure_does_not_break_litellm_stream(monkeypatch):
    """LiteLLM remains the authoritative stream parser."""
    app, calls = fixture_provider("openai")

    def fail_observation(self, chunk):
        raise ValueError("provider event is outside the optional meter dialect")

    monkeypatch.setattr(Meter, "feed", fail_observation)
    async with listening(app) as url:
        result = await invoke("openai", url, stream=True)

    assert len(calls) == 1
    assert result["choices"]
    assert result["usage"] == {"source": "unknown"}


async def test_meter_observation_failure_does_not_break_litellm_completion(monkeypatch):
    """A non-streaming response also stays under LiteLLM's response contract."""
    app, calls = fixture_provider("openai")

    def fail_observation(self, raw, *, stream):
        raise ValueError("optional usage observation failed")

    monkeypatch.setattr(Meter, "observe", fail_observation)
    async with listening(app) as url:
        result = await invoke("openai", url, stream=False)

    assert len(calls) == 1
    assert result["choices"][0]["message"]["content"] == "hello"
    assert result["usage"] is None


@pytest.mark.parametrize("adapter", list(MODELS))
async def test_sdk_eof_does_not_fabricate_billable_usage(adapter):
    app, calls = fixture_provider(adapter, broken=True)
    async with listening(app) as url:
        result = await invoke(adapter, url, stream=True)
    assert result["choices"] and result["usage"] == {"source": "unknown"}
    assert len(calls) == 1


@pytest.mark.parametrize("adapter", list(MODELS))
@pytest.mark.parametrize("stream", [False, True])
async def test_missing_upstream_usage_never_becomes_sdk_estimate(adapter, stream):
    app, _ = fixture_provider(adapter, metered=False)
    async with listening(app) as url:
        try:
            result = await invoke(adapter, url, stream=stream)
        except UpstreamFailure as exc:
            # Native schemas can require usage. A malformed result must remain uncertain,
            # rather than accepting the SDK's estimated replacement as a settled bill.
            assert adapter in ("anthropic", "gemini") and exc.uncertain
            return
    assert result["usage"] == ({"source": "unknown"} if stream else None)


@pytest.mark.parametrize("adapter", ["anthropic", "gemini"])
@pytest.mark.parametrize("stream", [False, True])
async def test_native_tool_conversion(adapter, stream):
    app, calls = fixture_provider(adapter, tools=True)
    async with listening(app) as url:
        result = await invoke(adapter, url, stream=stream, tools=True)
    assert "tool_calls" in str(result) and "lookup" in str(result)
    assert len(calls) == 1
    if not stream:
        converted, _ = chat.normalize(
            result, ChatInput(model="public", messages=[{"role": "user", "content": "hi"}]), "test"
        )
        assert converted["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "lookup"


async def test_sdk_never_fetches_private_images_or_sends_channel_secret_to_them():
    upstream, calls = fixture_provider("gemini")
    async with listening(upstream) as base:
        settings = Settings(_env_file=None, llm_allowed_private_origins=[base])
        with pytest.raises(UpstreamFailure) as exc:
            await sdk_runtime.complete(
                "gemini",
                base,
                "channel-secret",
                5,
                settings,
                {
                    "model": MODELS["gemini"],
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "https://127.0.0.1/private"},
                                }
                            ],
                        }
                    ],
                    "max_tokens": 16,
                },
            )
        assert exc.value.code == "image_unavailable" and not exc.value.uncertain
    assert calls == []


@pytest.mark.parametrize("adapter", list(MODELS))
async def test_error_redaction_and_no_sdk_retry(adapter):
    app, calls = fixture_provider(adapter, status=503)
    async with listening(app) as url:
        with pytest.raises(UpstreamFailure) as exc:
            await invoke(adapter, url)
    assert exc.value.upstream_status == 503 and exc.value.retryable
    assert "secret" not in str(exc.value) and len(calls) == 1


async def test_unknown_cache_ttl_and_partial_anthropic_usage():
    meter = Meter("anthropic")
    meter.observe(
        {"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 1}}},
        stream=True,
    )
    assert meter.usage() == {"source": "unknown"}

    meter.observe(
        {"usage": {"input_tokens": 3, "output_tokens": 1, "cache_creation_input_tokens": 10}},
        stream=False,
    )
    assert meter.usage() == {"source": "unknown"}


@pytest.mark.parametrize("adapter", ["anthropic", "gemini"])
async def test_native_unimplemented_operations_cannot_be_enabled(env, adapter):
    admin = await env.client()
    channel = await create_channel(
        admin,
        provider=adapter,
        base_url="https://example.test",
        models=[{"id": "vector-model"}],
        declared_apis=["embeddings"],
    )
    result = await admin.api.post(
        "/api/v1/llm/models",
        json={
            "name": "Native vector",
            "slug": "native-vector",
            "kind": "embedding",
            "retrieval": {"dimensions": 3, "embedding_space": "test-space"},
            "bindings": [
                {"channel_id": channel["id"], "upstream_id": "vector-model", "enabled": True}
            ],
            "access": {
                "enabled": True,
                "audience": "organization",
                "channel_id": channel["id"],
                "upstream_id": "vector-model",
            },
        },
    )
    assert result.status_code == 409, result.text
    assert result.json()["error"]["code"] == "operation_unavailable"


@pytest.mark.parametrize(
    "adapter,priced_writes", [("anthropic", True), ("gemini", False), ("gemini", True)]
)
@pytest.mark.parametrize("stream", [False, True])
async def test_native_member_key_authorization_settlement_and_live_revocation(
    env, monkeypatch, adapter, stream, priced_writes
):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock(return_value=True))
    admin, member, other = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    await billing(admin)
    upstream, calls = fixture_provider(adapter)
    async with listening(upstream) as base:
        env.provider.settings.llm_allowed_private_origins = [base]
        channel = await create_channel(
            admin,
            provider=adapter,
            base_url=base,
            models=[{"id": MODELS[adapter]}],
            declared_apis=["chat_completions"],
        )
        price = {
            "currency": "USD",
            "input": "1",
            "output": "1",
            "cache_read": "1",
        }
        if priced_writes:
            price.update(cache_write_5m="1", cache_write_1h="1")
        model = await create_model(
            admin,
            context_window=1000,
            max_output=32,
            capabilities={"streaming": "supported", "tools": "supported"},
            bindings=[
                {"channel_id": channel["id"], "upstream_id": MODELS[adapter], "enabled": True}
            ],
            budget_price=price,
            access={
                "enabled": True,
                "audience": "selected",
                "member_ids": [str(member.member.id)],
                "channel_id": channel["id"],
                "upstream_id": MODELS[adapter],
            },
        )
        key, _ = await create_key(member)
        denied_key, _ = await create_key(other)
        async with native_client(env) as api:
            request = payload(model, stream=stream)
            denied = await api.post(
                "/api/llm/v1/chat/completions", json=request, headers=headers(denied_key)
            )
            assert denied.status_code in (403, 404) and not calls
            response = await api.post(
                "/api/llm/v1/chat/completions", json=request, headers=headers(key)
            )
            assert response.status_code == 200, response.text
            if stream:
                assert "[DONE]" in response.text and '"error"' not in response.text
            else:
                assert response.json()["choices"][0]["message"]["content"] == "hello"
            rows = await entries(admin)
            assert len(rows) == 1 and len(calls) == 1
            if adapter == "gemini" and priced_writes:
                # Gemini did not report these cache-write buckets; SDK default
                # zero cannot substantiate an explicitly priced usage field.
                assert rows[0]["status"] == "review", rows
                assert rows[0]["points"] is None
                assert Decimal(rows[0]["reserved_points"]) > 0
                assert "cache_write_5m_tokens" not in rows[0]["usage"]
                assert "cache_write_1h_tokens" not in rows[0]["usage"]
            else:
                assert rows[0]["status"] == "settled", rows
                assert rows[0]["points"] == ("0.0103" if adapter == "anthropic" else "0.0105")
                assert rows[0]["reserved_points"] == "0"
            await update(
                admin,
                model,
                access={**model["access"], "audience": "administrators", "member_ids": []},
            )
            revoked = await api.post(
                "/api/llm/v1/chat/completions", json=request, headers=headers(key)
            )
            assert revoked.status_code in (403, 404) and len(calls) == 1
