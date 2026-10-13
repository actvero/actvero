"""Saved connection targets through real SDK adapters and pinned in-memory HTTP."""

import json
import wave
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from fastapi import FastAPI, Request
from llm_billing_helpers import billing
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model
from test_llm_channels import create as create_channel
from test_llm_execution import payload
from test_mcp import listening

from app.core.config import Settings
from app.core.outbound import PinnedTransport
from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.providers import (
    PROVIDERS,
    openai_compatible,
    sdk,
    sdk_images,
    sdk_retrieval,
    sdk_runtime,
    sdk_speech,
    sdk_transport,
)
from app.modules.llm.providers.base import ModelListing
from app.modules.llm.providers.connection import (
    compatibility_base_url,
    resolve_stored_connection,
    stored_connection,
)
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.schemas import ChannelImageProbe, ChannelSpeechProbe

pytestmark = pytest.mark.asyncio
env = identity_env
ORIGIN = "http://127.0.0.1:8765"
OLD_BASE = ORIGIN + "/old"
ROOT = ORIGIN + "/proxy"
CONNECTION = {"address_mode": "service_root", "service_root": ROOT, "resolver_version": 1}


class BytesStream(httpx2.AsyncByteStream):
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def __aiter__(self):
        yield self.data


def wav() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0" * 800)
    return output.getvalue()


def response(provider: str, operation: str) -> httpx2.Response:
    if operation == "speech":
        return httpx2.Response(
            200, headers={"content-type": "audio/wav"}, stream=BytesStream(wav())
        )
    if operation == "directory":
        value = {"data": [{"id": "test-model"}]}
    elif provider == "anthropic":
        value = {
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "test-model",
            "content": [{"type": "text", "text": "ok"}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 2, "output_tokens": 1},
        }
    elif provider == "gemini":
        value = {
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "ok"}]},
                    "finishReason": "STOP",
                    "index": 0,
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 2,
                "candidatesTokenCount": 1,
                "totalTokenCount": 3,
            },
        }
    elif operation == "embedding":
        value = {
            "data": [{"index": 0, "embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 2, "total_tokens": 2},
        }
    elif operation == "rerank":
        value = {"results": [{"index": 0, "relevance_score": 0.8}], "usage": {"total_tokens": 2}}
    elif operation == "image_generation":
        value = {"created": 1, "data": [{"b64_json": "eA=="}]}
    else:
        value = {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"},
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }
    return httpx2.Response(
        200,
        headers={"content-type": "application/json"},
        stream=BytesStream(json.dumps(value).encode()),
    )


def capture(monkeypatch, provider: str, operation: str, *, status: int = 200):
    calls: list[tuple[str, str, dict[str, str]]] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        calls.append((request.method, str(request.url), dict(request.headers)))
        if status != 200:
            return httpx2.Response(status, stream=BytesStream(b"{}"))
        return response(provider, operation)

    class CapturingPinnedTransport(PinnedTransport):
        def __init__(self, base, resolver, *, max_bytes=4_000_000, on_send=None):
            super().__init__(base, resolver, max_bytes=max_bytes, on_send=on_send)
            self.inner = httpx2.MockTransport(reply)

    for module in (openai_compatible, sdk_transport):
        monkeypatch.setattr(module, "PinnedTransport", CapturingPinnedTransport)
    return calls


def settings() -> Settings:
    return Settings(_env_file=None, llm_allowed_private_origins=[ORIGIN])


def selected(provider: str, operation: str, *, connection=CONNECTION, stream=False):
    return resolve_stored_connection(
        provider, OLD_BASE, connection, model="test-model", operations=(operation,), stream=stream
    ).operation_targets[0]


async def test_saved_connection_projection_and_strict_json():
    assert (
        compatibility_base_url("openai-compatible", stored_connection(OLD_BASE, CONNECTION))
        == ROOT + "/v1"
    )
    assert compatibility_base_url("anthropic", stored_connection(OLD_BASE, CONNECTION)) == ROOT
    assert resolve_stored_connection("gemini", OLD_BASE, {}).directory_url == (
        OLD_BASE + "/v1beta/models"
    )
    for invalid in ({"resolver_version": 1}, {"address_mode": "service_root", "secret": "x"}, []):
        with pytest.raises(ValueError):
            stored_connection(OLD_BASE, invalid)


@pytest.mark.parametrize("provider", ["openai-compatible", "anthropic", "gemini"])
async def test_saved_chat_target_overrides_old_base(monkeypatch, provider):
    calls = capture(monkeypatch, provider, "chat")
    target = selected(provider, "chat")
    result = await sdk_runtime.complete(
        target.sdk_provider,
        OLD_BASE,
        "fake-key",
        5,
        settings(),
        {"model": "test-model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8},
        target=target,
    )
    assert result["choices"][0]["message"]["content"] == "ok"
    assert [(method, url) for method, url, _ in calls] == [("POST", target.url)]
    assert "/old/" not in calls[0][1]
    if provider == "anthropic":
        assert calls[0][2]["x-api-key"] == "fake-key"
    elif provider == "gemini":
        assert calls[0][2]["x-goog-api-key"] == "fake-key"
    else:
        assert calls[0][2]["authorization"] == "Bearer fake-key"


async def test_anthropic_custom_prefix_uses_exact_sdk_mapping(monkeypatch):
    calls = capture(monkeypatch, "anthropic", "chat")
    config = {**CONNECTION, "api_prefix": "/edge/v2"}
    target = selected("anthropic", "chat", connection=config)
    assert target.sdk_expected_url == ROOT + "/v1/messages"
    assert target.url == ROOT + "/edge/v2/messages"
    await sdk_runtime.complete(
        "anthropic",
        OLD_BASE,
        "fake-key",
        5,
        settings(),
        {"model": "test-model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8},
        target=target,
    )
    assert [(method, url) for method, url, _ in calls] == [("POST", target.url)]


async def test_gemini_stream_uses_version_and_sse_query(monkeypatch):
    calls = capture(monkeypatch, "gemini", "chat", status=500)
    target = selected("gemini", "chat", stream=True)
    with pytest.raises(UpstreamFailure):
        async for _ in sdk_runtime.events(
            "gemini",
            OLD_BASE,
            "fake-key",
            5,
            settings(),
            {
                "model": "test-model",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 8,
                "stream": True,
            },
            "test-model",
            "request",
            sdk_runtime.chat.StreamState(),
            target=target,
        ):
            pass
    assert [(method, url) for method, url, _ in calls] == [("POST", target.url)]
    assert target.url.endswith("/v1beta/models/test-model:streamGenerateContent?alt=sse")


@pytest.mark.parametrize("operation", ["embedding", "rerank"])
async def test_retrieval_exact_target_and_single_send(monkeypatch, operation):
    calls = capture(monkeypatch, "openai-compatible", operation)
    target = selected("openai-compatible", operation)
    path = "/embeddings" if operation == "embedding" else "/rerank"
    payload = (
        {"model": "test-model", "input": ["hi"]}
        if operation == "embedding"
        else {"model": "test-model", "query": "hi", "documents": ["hi"], "top_n": 1}
    )
    raw = await sdk_retrieval.post(
        OLD_BASE, path, "fake-key", 5, settings(), payload, target=target
    )
    assert ("data" if operation == "embedding" else "results") in raw
    assert [(method, url) for method, url, _ in calls] == [("POST", target.url)]
    if operation == "rerank":
        assert target.sdk_expected_url == ROOT + "/v1/v1/rerank"
        assert target.url == ROOT + "/v1/rerank"


async def test_image_and_speech_targets(monkeypatch):
    image_calls = capture(monkeypatch, "openai-compatible", "image_generation")
    image_target = selected("openai-compatible", "image_generation")
    result = await sdk_images.generate(
        ChannelImageProbe(version=1, id="test-model", operation="image_generation", prompt="hi"),
        OLD_BASE,
        "fake-key",
        5,
        settings(),
        target=image_target,
    )
    assert result.image == {"b64_json": "eA=="}
    assert [(method, url) for method, url, _ in image_calls] == [("POST", image_target.url)]

    speech_calls = capture(monkeypatch, "openai-compatible", "speech")
    speech_target = selected("openai-compatible", "speech")
    audio = await sdk_speech.generate(
        ChannelSpeechProbe(
            version=1, id="test-model", operation="speech", input="hi", voice="alloy"
        ),
        OLD_BASE,
        "fake-key",
        5,
        settings(),
        target=speech_target,
    )
    assert audio.duration_ms == 50
    assert [(method, url) for method, url, _ in speech_calls] == [("POST", speech_target.url)]


async def test_saved_directory_and_diagnostic_consume_new_target(monkeypatch):
    directory_calls = capture(monkeypatch, "openai-compatible", "directory")
    listing = await PROVIDERS["openai-compatible"].list_models(
        OLD_BASE,
        "fake-key",
        5,
        settings(),
        connection=CONNECTION,
    )
    assert [model.id for model in listing.models] == ["test-model"]
    assert [(method, url) for method, url, _ in directory_calls] == [("GET", ROOT + "/v1/models")]
    chat_calls = capture(monkeypatch, "openai-compatible", "chat")
    target = selected("openai-compatible", "chat")
    diagnostic = await sdk.test_chat(
        adapter="openai",
        base=OLD_BASE,
        key="fake-key",
        model="test-model",
        prompt="hi",
        max_output=8,
        timeout=5,
        settings=settings(),
        request_id=uuid4(),
        target=target,
    )
    assert diagnostic.ok
    assert [(method, url) for method, url, _ in chat_calls] == [("POST", target.url)]


async def test_legacy_gemini_directory_and_chat_keep_distinct_old_paths(monkeypatch):
    calls = capture(monkeypatch, "gemini", "chat")
    target = selected("gemini", "chat", connection={})
    assert target.url == OLD_BASE + "/models/test-model:generateContent"
    assert resolve_stored_connection("gemini", OLD_BASE, {}).directory_url == (
        OLD_BASE + "/v1beta/models"
    )
    await sdk_runtime.complete(
        "gemini",
        OLD_BASE,
        "fake-key",
        5,
        settings(),
        {"model": "test-model", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8},
    )
    assert [(method, url) for method, url, _ in calls] == [("POST", target.url)]


async def test_persisted_address_reaches_admin_diagnostic_and_member_runtime(env, monkeypatch):
    """The real API and DB must hand the saved address to both SDK consumers."""
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock(return_value=True))
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    await billing(admin)
    upstream, calls = FastAPI(), []

    @upstream.post("/{path:path}")
    async def reply(path: str, request: Request):
        calls.append((path, dict(request.headers), await request.json()))
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"},
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            name="新地址全链",
            base_url=root + "/old/v1",
            connection={
                "address_mode": "service_root",
                "service_root": root + "/proxy",
                "api_prefix": "/edge/v2",
                "resolver_version": 1,
            },
            api_key="fake-key",
            models=[{"id": "test-model"}],
            declared_apis=["chat_completions"],
        )
        assert channel["connection"]["api_prefix"] == "/edge/v2"
        diagnostic = await admin.api.post(
            f"/api/v1/llm/channels/{channel['id']}/test",
            json={
                "version": channel["version"],
                "id": "test-model",
                "operation": "chat",
                "prompt": "hi",
                "max_output_tokens": 8,
            },
        )
        assert diagnostic.status_code == 200, diagnostic.text
        assert diagnostic.json()["ok"], diagnostic.text
        model = await create_model(
            admin,
            context_window=1000,
            max_output=32,
            capabilities={"streaming": "supported"},
            bindings=[{"channel_id": channel["id"], "upstream_id": "test-model", "enabled": True}],
            budget_price={"currency": "USD", "input": "1", "output": "1"},
            access={
                "enabled": True,
                "audience": "selected",
                "member_ids": [str(member.member.id)],
                "channel_id": channel["id"],
                "upstream_id": "test-model",
            },
        )
        key, _ = await create_key(member)
        async with native_client(env) as api:
            completion = await api.post(
                "/api/llm/v1/chat/completions",
                json=payload(model),
                headers=headers(key),
            )
            assert completion.status_code == 200, completion.text
            assert completion.json()["choices"][0]["message"]["content"] == "ok"
            disabled = await admin.api.put(
                f"/api/v1/llm/channels/{channel['id']}/status",
                json={"version": channel["version"], "manual_enabled": False},
            )
            assert disabled.status_code == 200, disabled.text
            assert disabled.json()["manual_enabled"] is False
            denied_member = await api.post(
                "/api/llm/v1/chat/completions",
                json=payload(model),
                headers=headers(key),
            )
            assert denied_member.status_code == 409
            assert len(calls) == 2
            unselected = await admin.api.post(
                f"/api/v1/llm/models/{model['id']}/test/chat",
                json=payload(model),
            )
            assert unselected.status_code == 409
            assert len(calls) == 2
            selected = await admin.api.post(
                f"/api/v1/llm/models/{model['id']}/test/chat",
                params={"channel_id": channel["id"], "upstream_id": "test-model"},
                json=payload(model),
            )
            assert selected.status_code == 200, selected.text
            still_disabled = await admin.api.get(f"/api/v1/llm/channels/{channel['id']}")
            assert still_disabled.json()["manual_enabled"] is False
    assert [path for path, _, _ in calls] == [
        "proxy/edge/v2/chat/completions",
        "proxy/edge/v2/chat/completions",
        "proxy/edge/v2/chat/completions",
    ]
    assert all(item[1]["authorization"] == "Bearer fake-key" for item in calls)


async def test_new_gemini_address_rejects_model_that_cannot_form_sdk_target(env):
    admin = await env.client()
    result = await admin.api.post(
        "/api/v1/llm/channels",
        json={
            "name": "Invalid Gemini path model",
            "provider": "gemini",
            "connection": {
                "address_mode": "service_root",
                "service_root": "https://gemini.example/proxy",
            },
            "api_key": "fake-key",
            "models": [{"id": "models/test-model"}],
        },
    )
    assert result.status_code == 422, result.text


async def test_draft_changed_address_requires_new_key_before_any_directory_io(env, monkeypatch):
    admin = await env.client()
    old = await create_channel(
        admin,
        name="Old target",
        base_url="https://old.example/v1",
        api_key="old-fake-key",
    )
    directory = AsyncMock(return_value=ModelListing([]))
    monkeypatch.setattr(PROVIDERS["openai-compatible"], "list_models", directory)
    draft = {
        "channel_id": old["id"],
        "version": old["version"],
        "provider": "openai-compatible",
        "base_url": old["base_url"],
        "connection": {
            "address_mode": "service_root",
            "service_root": "https://new.example/proxy",
        },
    }
    denied = await admin.api.post("/api/v1/llm/channel-drafts/inspect", json=draft)
    assert denied.status_code == 422
    directory.assert_not_awaited()
    allowed = await admin.api.post(
        "/api/v1/llm/channel-drafts/inspect", json=draft | {"api_key": "new-fake-key"}
    )
    assert allowed.status_code == 200, allowed.text
    assert directory.await_args.args[0] == "https://new.example/proxy/v1"
    assert directory.await_args.args[1] == "new-fake-key"
    assert directory.await_args.kwargs["connection"]["service_root"] == "https://new.example/proxy"
