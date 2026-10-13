"""Versioned address contract and LiteLLM 1.102.1 URL capture, with no network."""

import json

import httpx
import httpx2
import pytest
from openai import APIError, AsyncOpenAI

from app.core.config import Settings
from app.core.outbound import PinnedTransport
from app.modules.llm.providers import PROVIDERS, openai_compatible
from app.modules.llm.providers.connection import (
    ChannelConnection,
    legacy_connection,
    resolve_connection,
)
from app.modules.llm.providers.sdk import ChannelHTTPHandler, litellm


def target(provider, connection, operation="chat", *, model="test-model", stream=False):
    return resolve_connection(
        provider, connection, model=model, operations=(operation,), stream=stream
    ).operation_targets[0]


def test_default_proxy_prefix_and_legacy_directory_contract():
    assert target("openai", ChannelConnection(address_mode="provider_default")).url == (
        "https://api.openai.com/v1/chat/completions"
    )
    root = ChannelConnection(address_mode="service_root", service_root="https://proxy.test/proxy/")
    resolved = resolve_connection("openai-compatible", root, model="test-model")
    assert resolved.directory_url == "https://proxy.test/proxy/v1/models"
    assert [t.url for t in resolved.operation_targets] == [
        "https://proxy.test/proxy/v1/chat/completions",
        "https://proxy.test/proxy/v1/embeddings",
        "https://proxy.test/proxy/v1/rerank",
        "https://proxy.test/proxy/v1/images/generations",
        "https://proxy.test/proxy/v1/audio/speech",
        "https://proxy.test/proxy/v1/audio/transcriptions",
    ]
    assert {t.method for t in resolved.operation_targets} == {"POST"}
    assert resolved.directory_method == "GET"
    custom = ChannelConnection(
        address_mode="service_root", service_root="https://proxy.test/proxy", api_prefix="/edge/v2"
    )
    assert (
        target("openai-compatible", custom).url
        == "https://proxy.test/proxy/edge/v2/chat/completions"
    )
    assert resolve_connection("openai-compatible", custom).directory_url == (
        "https://proxy.test/proxy/edge/v2/models"
    )
    old = legacy_connection("https://proxy.test/custom/v2/")
    assert old.legacy_base_url == "https://proxy.test/custom/v2/"
    assert target("openai-compatible", old).url == "https://proxy.test/custom/v2/chat/completions"
    assert (
        resolve_connection("openai-compatible", old).directory_url
        == "https://proxy.test/custom/v2/models"
    )
    assert resolve_connection("openai-compatible", old).warnings == ("legacy_base_preserved",)


def test_provider_specific_targets_and_legacy_gemini_split():
    assert resolve_connection(
        "deepseek", ChannelConnection(address_mode="provider_default")
    ).directory_url == ("https://api.deepseek.com/models")
    assert target("deepseek", ChannelConnection(address_mode="provider_default")).url == (
        "https://api.deepseek.com/chat/completions"
    )
    assert target("anthropic", ChannelConnection(address_mode="provider_default")).url == (
        "https://api.anthropic.com/v1/messages"
    )
    gemini = ChannelConnection(address_mode="provider_default")
    assert target("gemini", gemini).url == (
        "https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent"
    )
    assert target("gemini", gemini, stream=True).url.endswith(
        "/v1beta/models/test-model:streamGenerateContent?alt=sse"
    )
    old = legacy_connection("https://gateway.test/proxy")
    assert (
        resolve_connection("gemini", old).directory_url
        == "https://gateway.test/proxy/v1beta/models"
    )
    assert (
        target("gemini", old).url == "https://gateway.test/proxy/models/test-model:generateContent"
    )


def test_native_prefix_requires_only_an_exact_sdk_url_map():
    connection = ChannelConnection(
        address_mode="service_root",
        service_root="https://gateway.test/proxy",
        api_prefix="/edge/v2/",
    )
    anthropic = target("anthropic", connection)
    assert anthropic.url == "https://gateway.test/proxy/edge/v2/messages"
    assert anthropic.sdk_api_base == "https://gateway.test/proxy"
    assert anthropic.sdk_expected_url == "https://gateway.test/proxy/v1/messages"
    gemini = target("gemini", connection)
    assert gemini.sdk_api_base == "https://gateway.test/proxy/edge/v2"
    assert gemini.sdk_expected_url == gemini.url


def test_explicit_empty_prefix_overrides_provider_version():
    connection = ChannelConnection(
        address_mode="service_root", service_root="https://gateway.test/proxy", api_prefix=""
    )
    result = resolve_connection("openai-compatible", connection, operations=("chat",))
    assert result.directory_url == "https://gateway.test/proxy/models"
    assert result.operation_targets[0].url == "https://gateway.test/proxy/chat/completions"


def test_legacy_compatible_operations_keep_original_base_suffixes():
    suffixes = {
        "chat": "/chat/completions",
        "embedding": "/embeddings",
        "rerank": "/rerank",
        "image_generation": "/images/generations",
        "speech": "/audio/speech",
    }
    for provider, base, operations in (
        ("openai", "https://mock.test/v1", tuple(suffixes)),
        ("openai-compatible", "https://mock.test/custom/v2", tuple(suffixes)),
        ("siliconflow", "https://mock.test/v1", ("chat", "embedding", "rerank")),
        ("deepseek", "https://mock.test", ("chat", "embedding", "rerank")),
    ):
        result = resolve_connection(provider, legacy_connection(base), operations=operations)
        assert result.directory_url == base + "/models"
        assert {item.operation: item.url for item in result.operation_targets} == {
            operation: base + suffixes[operation] for operation in operations
        }


@pytest.mark.parametrize(
    "connection",
    [
        ChannelConnection(address_mode="service_root", service_root="https://h.test/v1"),
        ChannelConnection(address_mode="service_root", service_root="https://h.test/v1beta/"),
        ChannelConnection(
            address_mode="service_root", service_root="https://h.test/proxy/v1/models"
        ),
        ChannelConnection(address_mode="service_root", service_root="https://user:pass@h.test"),
        ChannelConnection(address_mode="service_root", service_root="https://h.test/?key=secret"),
        ChannelConnection(address_mode="service_root", service_root="https://h.test/#frag"),
        ChannelConnection(address_mode="service_root", service_root="https://h.test/%2fother"),
        ChannelConnection(address_mode="service_root", service_root="https://h.test/中文"),
        ChannelConnection(address_mode="service_root", service_root="https://h.test/a/../b"),
        ChannelConnection(
            address_mode="service_root", service_root="https://h.test", api_prefix="//other"
        ),
        ChannelConnection(
            address_mode="service_root", service_root="https://h.test", api_prefix="/../other"
        ),
        ChannelConnection(
            address_mode="service_root", service_root="https://h.test", api_prefix="/v1?key=x"
        ),
        ChannelConnection(
            address_mode="service_root", service_root="https://h.test", api_prefix="/中文"
        ),
        ChannelConnection(address_mode="provider_default", service_root="https://h.test"),
        ChannelConnection(address_mode="provider_default", resolver_version=2),
    ],
)
def test_unsafe_or_ambiguous_input_rejected(connection):
    with pytest.raises(ValueError):
        resolve_connection("openai", connection)


@pytest.mark.parametrize("address", ["https://x?", "https://x/#"])
@pytest.mark.parametrize("mode", ["service_root", "legacy_api_base"])
def test_empty_query_or_fragment_delimiter_rejected_in_all_modes(address, mode):
    connection = (
        ChannelConnection(address_mode="service_root", service_root=address)
        if mode == "service_root"
        else legacy_connection(address)
    )
    with pytest.raises(ValueError, match="分隔符"):
        resolve_connection("openai", connection, operations=("chat",))


def test_unknown_combinations_and_model_rejected():
    with pytest.raises(ValueError):
        resolve_connection("unknown", ChannelConnection(address_mode="provider_default"))
    with pytest.raises(ValueError):
        resolve_connection("openai-compatible", ChannelConnection(address_mode="provider_default"))
    with pytest.raises(ValueError):
        target("anthropic", ChannelConnection(address_mode="provider_default"), "embedding")
    with pytest.raises(ValueError):
        target(
            "openai", ChannelConnection(address_mode="provider_default"), "embedding", stream=True
        )
    with pytest.raises(ValueError):
        target("gemini", ChannelConnection(address_mode="provider_default"), model="models/other")


def _response(operation: str, provider: str) -> httpx.Response:
    if provider == "anthropic":
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 2, "output_tokens": 1},
            },
        )
    if provider == "gemini":
        return httpx.Response(
            200,
            json={
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
            },
        )
    if operation == "embedding":
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})
    if operation == "rerank":
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.8}]})
    if operation == "image_generation":
        return httpx.Response(200, json={"created": 1, "data": [{"b64_json": "eA=="}]})
    if operation == "speech":
        return httpx.Response(200, content=b"RIFFxxxxWAVE", headers={"content-type": "audio/wav"})
    return httpx.Response(
        200,
        json={
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
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "operation", "root"),
    [
        ("openai", "chat", "https://mock.test/proxy"),
        ("openai", "embedding", "https://mock.test/proxy"),
        ("openai", "rerank", "https://mock.test/proxy"),
        ("openai", "image_generation", "https://mock.test/proxy"),
        ("openai", "speech", "https://mock.test/proxy"),
        ("openai-compatible", "chat", "https://mock.test/proxy"),
        ("openai-compatible", "embedding", "https://mock.test/proxy"),
        ("openai-compatible", "rerank", "https://mock.test/proxy"),
        ("openai-compatible", "image_generation", "https://mock.test/proxy"),
        ("openai-compatible", "speech", "https://mock.test/proxy"),
        ("siliconflow", "chat", "https://mock.test/proxy"),
        ("siliconflow", "embedding", "https://mock.test/proxy"),
        ("siliconflow", "rerank", "https://mock.test/proxy"),
        ("deepseek", "chat", "https://mock.test/proxy"),
        ("deepseek", "embedding", "https://mock.test/proxy"),
        ("deepseek", "rerank", "https://mock.test/proxy"),
        ("anthropic", "chat", "https://mock.test/proxy"),
        ("gemini", "chat", "https://mock.test/proxy"),
    ],
)
async def test_real_locked_sdk_posts_to_resolved_target(provider, operation, root):
    resolved = resolve_connection(
        provider,
        ChannelConnection(address_mode="service_root", service_root=root),
        model="test-model",
        operations=(operation,),
    )
    target = resolved.operation_targets[0]
    captured: list[tuple[str, str]] = []

    def reply(request: httpx.Request) -> httpx.Response:
        captured.append((request.method, str(request.url)))
        return _response(operation, provider)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as http:
        client = (
            AsyncOpenAI(
                api_key="fake", base_url=target.sdk_api_base, http_client=http, max_retries=0
            )
            if target.sdk_provider == "openai"
            else ChannelHTTPHandler(http)
        )
        kwargs = {
            "model": "test-model",
            "custom_llm_provider": target.sdk_provider,
            "api_base": target.sdk_api_base,
            "api_key": "fake",
            "client": client,
            "num_retries": 0,
            "max_retries": 0,
            "caching": False,
            "drop_params": False,
        }
        if operation == "chat":
            await litellm.acompletion(
                **kwargs, messages=[{"role": "user", "content": "hi"}], max_tokens=8
            )
        elif operation == "embedding":
            await litellm.aembedding(**kwargs, input=["hi"])
        elif operation == "rerank":
            await litellm.arerank(
                **kwargs, query="hi", documents=["hi"], top_n=1, return_documents=False
            )
        elif operation == "image_generation":
            await litellm.aimage_generation(
                **{**kwargs, "model": "openai/test-model"}, prompt="hi", n=1
            )
        else:
            await litellm.aspeech(
                **{**kwargs, "model": "openai/test-model"},
                input="hi",
                voice="alloy",
                response_format="wav",
            )
    assert captured == [("POST", target.sdk_expected_url)]
    version = "v1beta" if provider == "gemini" else "" if provider == "deepseek" else "v1"
    stem = root + ("/" + version if version else "")
    assert target.url.startswith(stem + "/")
    assert resolved.directory_url == stem + "/models"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai-compatible", "anthropic", "gemini"])
async def test_real_locked_sdk_stream_target(provider):
    target = resolve_connection(
        provider,
        ChannelConnection(address_mode="service_root", service_root="https://mock.test/proxy"),
        model="test-model",
        operations=("chat",),
        stream=True,
    ).operation_targets[0]
    captured: list[tuple[str, str]] = []

    def reply(request: httpx.Request) -> httpx.Response:
        captured.append((request.method, str(request.url)))
        return httpx.Response(500, json={"error": {"message": "capture only"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as http:
        client = (
            AsyncOpenAI(
                api_key="fake", base_url=target.sdk_api_base, http_client=http, max_retries=0
            )
            if target.sdk_provider == "openai"
            else ChannelHTTPHandler(http)
        )
        with pytest.raises(APIError):
            result = await litellm.acompletion(
                model="test-model",
                custom_llm_provider=target.sdk_provider,
                api_base=target.sdk_api_base,
                api_key="fake",
                client=client,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=8,
                stream=True,
                num_retries=0,
                max_retries=0,
                caching=False,
                drop_params=False,
            )
            await anext(result)
    assert captured == [("POST", target.sdk_expected_url)]
    assert target.url == target.sdk_expected_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "old_base", "expected_path"),
    [
        ("openai", "https://mock.test/v1", "/v1/chat/completions"),
        ("openai-compatible", "https://mock.test/custom/v2", "/custom/v2/chat/completions"),
        ("siliconflow", "https://mock.test/v1", "/v1/chat/completions"),
        ("deepseek", "https://mock.test", "/chat/completions"),
        ("anthropic", "https://mock.test", "/v1/messages"),
        ("gemini", "https://mock.test", "/models/test-model:generateContent"),
    ],
)
async def test_legacy_matches_actual_locked_sdk_target(provider, old_base, expected_path):
    resolved_target = resolve_connection(
        provider, legacy_connection(old_base), model="test-model", operations=("chat",)
    ).operation_targets[0]
    calls = []

    def reply(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        return _response("chat", provider)

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as http:
        client = (
            AsyncOpenAI(
                api_key="fake",
                base_url=resolved_target.sdk_api_base,
                http_client=http,
                max_retries=0,
            )
            if resolved_target.sdk_provider == "openai"
            else ChannelHTTPHandler(http)
        )
        await litellm.acompletion(
            model="test-model",
            custom_llm_provider=resolved_target.sdk_provider,
            api_base=resolved_target.sdk_api_base,
            api_key="fake",
            client=client,
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=8,
            num_retries=0,
            max_retries=0,
            caching=False,
            drop_params=False,
        )
    assert resolved_target.url == "https://mock.test" + expected_path
    assert calls == [("POST", resolved_target.url)]


@pytest.mark.asyncio
async def test_directory_preview_is_a_single_get_with_no_secret_in_url():
    result = resolve_connection(
        "openai-compatible",
        ChannelConnection(address_mode="service_root", service_root="https://mock.test/proxy"),
        operations=(),
    )
    calls = []

    def reply(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(reply), trust_env=False) as client:
        response = await client.request(result.directory_method, result.directory_url)
    assert response.json() == {"data": []}
    assert calls == [("GET", "https://mock.test/proxy/v1/models")]


def test_no_credentials_appear_in_preview():
    result = resolve_connection(
        "openai-compatible",
        ChannelConnection(address_mode="service_root", service_root="https://mock.test/proxy"),
    )
    assert "fake" not in json.dumps(result, default=lambda value: value.__dict__)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "base_path", "directory_path", "key"),
    [
        ("openai", "/v1", "/v1/models", "fake-key"),
        ("openai-compatible", "/custom/v2", "/custom/v2/models", "fake-key"),
        ("openai-compatible", "/custom/v2", "/custom/v2/models", None),
        ("siliconflow", "/v1", "/v1/models", "fake-key"),
        ("deepseek", "", "/models", "fake-key"),
        ("anthropic", "", "/v1/models", "fake-key"),
        ("gemini", "", "/v1beta/models", "fake-key"),
    ],
)
async def test_existing_directory_consumer_uses_resolved_legacy_target(
    provider, base_path, directory_path, key, monkeypatch
):
    calls = []
    transport_bases = []
    origin = "http://127.0.0.1:8765"

    class JsonStream(httpx2.AsyncByteStream):
        def __init__(self, payload):
            self.body = json.dumps(payload).encode()

        async def __aiter__(self):
            yield self.body

    def models(request: httpx2.Request) -> httpx2.Response:
        calls.append((request.method, request.url.path, dict(request.headers)))
        if provider == "gemini":
            return httpx2.Response(
                200,
                stream=JsonStream(
                    {"models": [{"name": "models/gemini-test"}], "nextPageToken": "next"}
                ),
            )
        return httpx2.Response(
            200,
            stream=JsonStream(
                {"data": [{"id": "test-model"}, {"id": "test-model"}], "has_more": True}
            ),
        )

    class CapturingPinnedTransport(PinnedTransport):
        def __init__(self, base, resolver):
            super().__init__(base, resolver)
            transport_bases.append(base)
            self.inner = httpx2.MockTransport(models)

    monkeypatch.setattr(openai_compatible, "PinnedTransport", CapturingPinnedTransport)
    listing = await PROVIDERS[provider].list_models(
        origin + base_path,
        key,
        5,
        Settings(_env_file=None, llm_allowed_private_origins=[origin]),
    )
    assert transport_bases == [origin + base_path]
    assert len(calls) == 1
    method, path, headers = calls[0]
    assert (method, path) == ("GET", directory_path)
    assert headers["accept-encoding"] == "identity"
    assert listing.partial
    assert [item.id for item in listing.models] == [
        "gemini-test" if provider == "gemini" else "test-model"
    ]
    if provider == "anthropic":
        assert headers["x-api-key"] == key
        assert headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in headers
    elif provider == "gemini":
        assert headers["x-goog-api-key"] == key
        assert "authorization" not in headers
    else:
        assert headers.get("authorization") == ("Bearer " + key if key else None)
