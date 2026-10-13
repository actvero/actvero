"""Locked LiteLLM + runtime transport checks for separate provider products.

Every outbound HTTP request is intercepted in memory. Provider-looking hostnames
are never resolved or contacted by these tests.
"""

import asyncio
import json
import os
from dataclasses import replace
from urllib.parse import urlsplit
from uuid import uuid4

import httpx2
import pytest
from fastapi import HTTPException

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DO_NOT_TRACK", "True")

from app.core.config import Settings  # noqa: E402
from app.core.outbound import PinnedTransport  # noqa: E402
from app.modules.llm.providers import (  # noqa: E402
    PROVIDERS,
    openai_compatible,
    sdk_runtime,
    sdk_transport,
)
from app.modules.llm.providers.attempt import AttemptTrace  # noqa: E402
from app.modules.llm.providers.chat import StreamState  # noqa: E402
from app.modules.llm.providers.connection import (  # noqa: E402
    ChannelConnection,
    resolve_connection,
)
from app.modules.llm.providers.retrieval import UpstreamFailure  # noqa: E402

PROFILES = {
    "aihubmix": ("https://aihubmix.com", "/v1"),
    "volcengine": ("https://ark.cn-beijing.volces.com", "/api/v3"),
    "zhipu": ("https://open.bigmodel.cn", "/api/paas/v4"),
    "moonshot": ("https://api.moonshot.cn", "/v1"),
    "qwen": ("https://maas.qianwenaiapi.com", "/compatible-mode/v1"),
    "qwen-token-plan": ("https://token-plan.maas.qianwenaiapi.com", "/compatible-mode/v1"),
}
MODEL = "Vendor/Model-v1"
TOOLS = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]


class BytesStream(httpx2.AsyncByteStream):
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def __aiter__(self):
        yield self.data


def settings() -> Settings:
    return Settings(_env_file=None)


def target_for(provider: str, *, stream: bool = False):
    return resolve_connection(
        provider,
        ChannelConnection(address_mode="provider_default"),
        operations=("chat",),
        stream=stream,
    ).operation_targets[0]


def reply(request: httpx2.Request, *, stream: bool, usage: bool, status: int) -> httpx2.Response:
    if status != 200:
        return httpx2.Response(
            status,
            headers={"content-type": "application/json", "retry-after": "7201"},
            stream=BytesStream(b'{"error":{"message":"private-key","code":"fixture_rejection"}}'),
        )
    raw_usage = {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}
    common = {"id": "local-test", "created": 1, "model": MODEL}
    if not stream:
        body = common | {
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "local answer"},
                }
            ],
        }
        if usage:
            body["usage"] = raw_usage
        return httpx2.Response(
            200,
            headers={"content-type": "application/json"},
            stream=BytesStream(json.dumps(body).encode()),
        )
    chunks = [
        common
        | {
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "local answer"},
                    "finish_reason": None,
                }
            ],
        },
        common
        | {
            "object": "chat.completion.chunk",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]
    if usage:
        chunks.append(
            common | {"object": "chat.completion.chunk", "choices": [], "usage": raw_usage}
        )
    body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
    return httpx2.Response(
        200, headers={"content-type": "text/event-stream"}, stream=BytesStream(body.encode())
    )


def memory_transport(monkeypatch, handler):
    """Keep the real PinnedTransport origin/size/send checks, replace only I/O/DNS."""
    sent: list[tuple[str, httpx2.Request]] = []

    class MemoryPinnedTransport(PinnedTransport):
        def __init__(self, base, resolver, *, max_bytes=4_000_000, on_send=None):
            super().__init__(base, resolver, max_bytes=max_bytes, on_send=on_send)

            async def local_address(_url):
                return "127.0.0.1"

            self.resolver = local_address
            self.inner = httpx2.MockTransport(handler)

        async def handle_async_request(self, request):
            sent.append((str(request.url), request))
            return await super().handle_async_request(request)

    monkeypatch.setattr(sdk_transport, "PinnedTransport", MemoryPinnedTransport)
    monkeypatch.setattr(openai_compatible, "PinnedTransport", MemoryPinnedTransport)
    return sent


@pytest.mark.parametrize("provider,root_prefix", PROFILES.items())
def test_profile_resolution_and_unsupported_operations(provider, root_prefix):
    root, prefix = root_prefix
    default = resolve_connection(
        provider, ChannelConnection(address_mode="provider_default"), operations=("chat",)
    )
    expected = root + prefix + "/chat/completions"
    assert default.operation_targets[0].url == expected
    assert default.operation_targets[0].sdk_provider == "openai"
    assert PROVIDERS[provider].sdk_provider == "openai"
    custom = resolve_connection(
        provider,
        ChannelConnection(address_mode="service_root", service_root="https://custom.example/root"),
        operations=("chat",),
    )
    assert (
        custom.operation_targets[0].url
        == "https://custom.example/root" + prefix + "/chat/completions"
    )
    explicit = resolve_connection(
        provider,
        ChannelConnection(
            address_mode="service_root",
            service_root="https://custom.example/root",
            api_prefix="/custom/v7",
        ),
        operations=("chat",),
    )
    assert (
        explicit.operation_targets[0].url
        == "https://custom.example/root/custom/v7/chat/completions"
    )
    for operation in ("embedding", "rerank", "image_generation", "speech"):
        with pytest.raises(ValueError, match="尚未接入"):
            resolve_connection(
                provider,
                ChannelConnection(address_mode="provider_default"),
                operations=(operation,),
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROFILES)
@pytest.mark.parametrize("stream", [False, True])
async def test_sdk_runtime_exact_chat_single_send_tools_and_raw_meter(
    monkeypatch, provider, stream
):
    target = target_for(provider, stream=stream)
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((dict(request.headers), body))
        return reply(request, stream=stream, usage=True, status=200)

    sent = memory_transport(monkeypatch, handler)
    trace = AttemptTrace()
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": "ping"}],
        "tools": TOOLS,
        "stream": stream,
        "max_tokens": 16,
    }
    if stream:
        payload["stream_options"] = {"include_usage": True}
        state = StreamState()
        chunks = [
            part
            async for part in sdk_runtime.events(
                "openai",
                "https://stale.invalid/v1",
                "channel-secret",
                5,
                settings(),
                payload,
                MODEL,
                str(uuid4()),
                state,
                target=target,
                trace=trace,
            )
        ]
        assert any("local answer" in str(part) for part in chunks)
        assert state.usage["source"] == "upstream"
        assert state.usage["input_tokens"] == 7
        assert state.usage["output_tokens"] == 2
    else:
        meter_raw = {}
        result = await sdk_runtime.complete(
            "openai",
            "https://stale.invalid/v1",
            "channel-secret",
            5,
            settings(),
            payload,
            target=target,
            trace=trace,
            meter_raw=meter_raw,
        )
        assert result["choices"][0]["message"]["content"] == "local answer"
        assert meter_raw == {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}
    assert len(sent) == len(seen) == 1
    assert sent[0][0] == PROFILES[provider][0] + PROFILES[provider][1] + "/chat/completions"
    headers, body = seen[0]
    assert headers["host"] == urlsplit(target.sdk_api_base).netloc
    assert headers["authorization"] == "Bearer channel-secret"
    assert body["model"] == MODEL and body["tools"] == TOOLS
    snapshot = trace.finish()
    assert snapshot["sent"] is True and snapshot["upstream_terminal"] is True
    fields = {item["field"]: item["value"] for item in snapshot["usage_evidence"]}
    assert fields["raw_prompt_tokens"] == 7 and fields["raw_completion_tokens"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROFILES)
async def test_missing_raw_usage_stays_unknown(monkeypatch, provider):
    target = target_for(provider)
    sent = memory_transport(
        monkeypatch, lambda request: reply(request, stream=False, usage=False, status=200)
    )
    trace = AttemptTrace()
    meter_raw = {}
    response = await sdk_runtime.complete(
        "openai",
        target.sdk_api_base,
        "one-key",
        5,
        settings(),
        {"model": MODEL, "messages": [{"role": "user", "content": "ping"}]},
        target=target,
        trace=trace,
        meter_raw=meter_raw,
    )
    assert response["choices"][0]["finish_reason"] == "stop"
    assert meter_raw == {} and len(sent) == 1
    assert trace.snapshot()["usage_evidence"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429])
@pytest.mark.parametrize("provider", ["aihubmix", "qwen-token-plan"])
async def test_concurrent_keys_and_rejections_never_retry(monkeypatch, status, provider):
    target = target_for(provider)
    seen = []

    def handler(request):
        key = request.headers.get("authorization")
        seen.append(key)
        return reply(
            request, stream=False, usage=False, status=status if key == "Bearer bad-key" else 200
        )

    memory_transport(monkeypatch, handler)

    async def call(key):
        trace = AttemptTrace()
        try:
            await sdk_runtime.complete(
                "openai",
                target.sdk_api_base,
                key,
                5,
                settings(),
                {"model": MODEL, "messages": [{"role": "user", "content": "ping"}]},
                target=target,
                trace=trace,
            )
            return trace, None
        except UpstreamFailure as error:
            return trace, error

    good, bad = await asyncio.gather(call("good-key"), call("bad-key"))
    assert sorted(seen) == ["Bearer bad-key", "Bearer good-key"]
    assert good[1] is None and bad[1] is not None
    assert bad[1].upstream_status == status
    assert bad[0].snapshot()["sent"] is True
    assert bad[0].snapshot()["retry_after_seconds"] == (7201 if status == 429 else None)


@pytest.mark.asyncio
async def test_cross_origin_target_is_rejected_before_inner_io(monkeypatch):
    target = replace(target_for("aihubmix"), url="https://other.example/v1/chat/completions")
    seen = []
    memory_transport(
        monkeypatch,
        lambda request: (
            seen.append(request) or reply(request, stream=False, usage=True, status=200)
        ),
    )
    with pytest.raises(HTTPException) as failure:
        await sdk_runtime.complete(
            "openai",
            target.sdk_api_base,
            "one-key",
            5,
            settings(),
            {"model": MODEL, "messages": [{"role": "user", "content": "ping"}]},
            target=target,
        )
    assert failure.value.status_code == 422 and seen == []


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", PROFILES)
async def test_directory_policy_before_io(monkeypatch, provider):
    seen = []
    sent = memory_transport(
        monkeypatch,
        lambda request: (
            seen.append((request.method, dict(request.headers)))
            or httpx2.Response(
                200,
                headers={"content-type": "application/json"},
                stream=BytesStream(b'{"data":[{"id":"Vendor/Model-v1"}]}'),
            )
        ),
    )
    if provider == "aihubmix":
        listing = await PROVIDERS[provider].list_models(
            PROFILES[provider][0] + PROFILES[provider][1],
            "directory-key",
            5,
            settings(),
            connection={"address_mode": "provider_default", "resolver_version": 1},
        )
        assert [model.id for model in listing.models] == [MODEL]
        assert sent[0][0] == "https://aihubmix.com/v1/models"
        assert len(seen) == 1 and seen[0][0] == "GET"
        assert seen[0][1]["authorization"] == "Bearer directory-key"
    else:
        with pytest.raises(HTTPException) as failure:
            await PROVIDERS[provider].list_models(
                PROFILES[provider][0] + PROFILES[provider][1],
                "directory-key",
                5,
                settings(),
                connection={"address_mode": "provider_default", "resolver_version": 1},
            )
        assert failure.value.status_code == 422
        assert "手动登记" in str(failure.value.detail)
        assert sent == seen == []
