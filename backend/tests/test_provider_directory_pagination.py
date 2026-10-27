"""Real directory adapters with in-memory HTTP; no vendor credentials or network."""

import json
from urllib.parse import parse_qs, urlsplit

import httpx2
import pytest
from fastapi import HTTPException
from test_provider_presets_runtime import BytesStream, memory_transport, settings

from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.connection import ChannelConnection, resolve_connection

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("provider", ["anthropic", "gemini", "aliyun-bailian"])
async def test_native_directory_pages_are_merged_without_losing_auth(monkeypatch, provider):
    requests = []

    def handler(request):
        requests.append(request)
        second = len(requests) == 2
        if provider == "anthropic":
            assert request.headers["x-api-key"] == "directory-secret"
            payload = {
                "data": [{"id": "second" if second else "first"}],
                "last_id": "second" if second else "first",
                "has_more": not second,
            }
        elif provider == "gemini":
            assert request.headers["x-goog-api-key"] == "directory-secret"
            payload = {"models": [{"name": "models/second" if second else "models/first"}]}
            if not second:
                payload["nextPageToken"] = "opaque/+cursor"
        else:
            assert request.headers["authorization"] == "Bearer directory-secret"
            payload = {
                "output": {
                    "models": [{"model": "second" if second else "first"}],
                    "page_no": 2 if second else 1,
                    "page_size": 100,
                    "total": 101,
                }
            }
        return httpx2.Response(200, stream=BytesStream(json.dumps(payload).encode()))

    sent = memory_transport(monkeypatch, handler)
    resolved = resolve_connection(provider, ChannelConnection(address_mode="provider_default"))
    listing = await PROVIDERS[provider].list_models(
        PROVIDERS[provider].info.default_base_url,
        "directory-secret",
        5,
        settings(),
        connection={"address_mode": "provider_default"},
    )
    assert [m.id for m in listing.models] == ["first", "second"]
    assert not listing.partial
    assert len(sent) == 2
    assert all(
        urlsplit(url)._replace(query="").geturl() == resolved.directory_url for url, _ in sent
    )
    second_query = parse_qs(urlsplit(sent[1][0]).query)
    assert (
        second_query
        == {
            "anthropic": {"limit": ["100"], "after_id": ["first"]},
            "gemini": {"pageSize": ["100"], "pageToken": ["opaque/+cursor"]},
            "aliyun-bailian": {"page_no": ["2"], "page_size": ["100"]},
        }[provider]
    )


@pytest.mark.parametrize("failure", ["repeated", "credential", "http", "invalid"])
async def test_directory_continuation_failure_never_becomes_static_models(monkeypatch, failure):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 2 and failure == "http":
            return httpx2.Response(401, text="directory-secret")
        if calls == 2 and failure == "invalid":
            return httpx2.Response(200, stream=BytesStream(b'{"error":"directory-secret"}'))
        payload = {
            "models": [{"name": "models/first"}],
            "nextPageToken": "directory-secret" if failure == "credential" else "repeated",
        }
        return httpx2.Response(200, stream=BytesStream(json.dumps(payload).encode()))

    memory_transport(monkeypatch, handler)
    with pytest.raises(HTTPException) as error:
        await PROVIDERS["gemini"].list_models(
            "https://generativelanguage.googleapis.com", "directory-secret", 5, settings()
        )
    assert error.value.status_code == 502
    assert "directory-secret" not in str(error.value.detail)
    assert calls <= 2


async def test_pagination_is_bounded_and_reports_partial(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        payload = {
            "models": [{"name": f"models/model-{calls}"}],
            "nextPageToken": f"page-{calls}",
        }
        return httpx2.Response(200, stream=BytesStream(json.dumps(payload).encode()))

    memory_transport(monkeypatch, handler)
    listing = await PROVIDERS["gemini"].list_models(
        "https://generativelanguage.googleapis.com", "directory-secret", 5, settings()
    )
    assert calls == 10 and len(listing.models) == 10 and listing.partial


@pytest.mark.parametrize(
    "provider,prefix",
    [
        ("volcengine-agent-plan", "/api/plan/v3"),
        ("volcengine-coding-plan", "/api/coding/v3"),
    ],
)
async def test_plan_directory_never_uses_paygo_endpoint(monkeypatch, provider, prefix):
    sent = memory_transport(
        monkeypatch,
        lambda request: httpx2.Response(200, stream=BytesStream(b'{"data":[{"id":"seat-model"}]}')),
    )
    listing = await PROVIDERS[provider].list_models(
        PROVIDERS[provider].info.default_base_url,
        "plan-secret",
        5,
        settings(),
        connection={"address_mode": "provider_default"},
    )
    assert [m.id for m in listing.models] == ["seat-model"]
    assert sent[0][0] == "https://ark.cn-beijing.volces.com" + prefix + "/models"
    assert sent[0][1].headers["authorization"] == "Bearer plan-secret"


async def test_bailian_custom_compatible_target_is_preserved(monkeypatch):
    sent = memory_transport(
        monkeypatch,
        lambda request: httpx2.Response(
            200, stream=BytesStream(b'{"data":[{"id":"private-model"}]}')
        ),
    )
    listing = await PROVIDERS["aliyun-bailian"].list_models(
        "https://proxy.example/gateway/v2",
        "directory-secret",
        5,
        settings(),
        connection={
            "address_mode": "service_root",
            "service_root": "https://proxy.example/gateway",
            "api_prefix": "/v2",
        },
    )
    assert [m.id for m in listing.models] == ["private-model"]
    assert sent[0][0] == "https://proxy.example/gateway/v2/models"
