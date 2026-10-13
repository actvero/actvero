import asyncio
import json
from unittest.mock import AsyncMock

import httpx2
import pytest
from fastapi import HTTPException
from test_identity_access import env as identity_env
from test_llm_catalog import BASE, CONFIG, create

from app.core.config import Settings
from app.core.outbound import LimitedStream
from app.modules.llm import reference_catalog as reference

env = identity_env
pytestmark = pytest.mark.asyncio
PATH = "/api/v1/llm/reference-models"
OPTIONS = [
    {"type": "toggle"},
    {"type": "effort", "values": [None, "none", "low", "high"]},
    {"type": "budget_tokens", "min": -1, "max": 8192},
]
PUBLIC = {
    "openai": {
        "name": "OpenAI",
        "env": ["DO_NOT_EXPOSE"],
        "api": "https://do-not-follow.test",
        "models": {
            "example-model": {
                "name": "Example",
                "reasoning": True,
                "reasoning_options": OPTIONS,
                "tool_call": False,
                "limit": {"context": 32000, "output": 8000},
                "modalities": {"input": ["text", "image"]},
                "cost": {
                    "input": 2,
                    "output": 8,
                    "cache_read": 0,
                    "cache_write": 4,
                    "tiers": [{"input": 10}],
                },
            }
        },
    }
}


async def test_public_parser_preserves_unknown_and_price_boundaries():
    payload = json.dumps(PUBLIC).replace('"input": 2,', '"input": 0.000000000001,')
    models, skipped = reference.parse_catalog(payload.encode())
    assert skipped == 0
    model = models[0]
    assert model.capabilities.streaming == "unknown"
    assert model.capabilities.structured_output == "unknown"
    assert model.capabilities.tools == "unsupported"
    assert model.capabilities.vision == "supported"
    assert [o.model_dump() for o in model.reasoning_options] == OPTIONS
    assert model.price.model_dump(mode="json")["input"] == "0.000000000001"
    assert model.price.cache_read == 0
    assert model.price.cache_write_5m is None and model.price.cache_write_1h is None
    assert len(model.price_notes) == 2
    assert "DO_NOT_EXPOSE" not in model.model_dump_json()
    assert "do-not-follow" not in model.model_dump_json()
    invalid = json.loads(json.dumps(PUBLIC))
    invalid["openai"]["models"]["bad"] = {
        "name": "Bad",
        "reasoning": True,
        "reasoning_options": [{"type": "unrecognized"}],
    }
    assert reference.parse_catalog(json.dumps(invalid).encode())[1] == 1
    with pytest.raises(ValueError):
        reference.parse_catalog(b'{"unexpected": 42}')


async def test_cache_single_fetch_stale_backoff_and_expiration(monkeypatch):
    fetch = AsyncMock(return_value=json.dumps(PUBLIC).encode())
    monkeypatch.setattr(reference, "fetch_catalog", fetch)
    cache = reference.ReferenceCache()
    settings = Settings()
    result = await asyncio.gather(*(cache.get(settings) for _ in range(6)))
    assert fetch.await_count == 1
    assert all(not row[2] for row in result)
    fetch.side_effect = TimeoutError()
    cache.loaded_at -= reference.TTL + 1
    assert (await cache.get(settings))[2] is True
    await cache.get(settings)
    assert fetch.await_count == 2
    cache.loaded_at -= reference.MAX_STALE
    with pytest.raises(HTTPException) as error:
        await cache.get(settings)
    assert error.value.status_code == 503
    cold = reference.ReferenceCache()
    for _ in range(2):
        with pytest.raises(HTTPException):
            await cold.get(settings)
    assert fetch.await_count == 3


@pytest.mark.parametrize(
    "status, headers, payload, accepted",
    [
        (200, {}, b'{"ok":1}', True),
        (302, {"location": "http://127.0.0.1/private"}, b"", False),
        (200, {"content-encoding": "gzip"}, b"compressed", False),
        (200, {}, b"oversized payload", False),
    ],
)
async def test_fetch_is_fixed_bounded_and_credential_free(
    monkeypatch, status, headers, payload, accepted
):
    class Stream(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield payload

    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == reference.URL
        assert request.headers["accept-encoding"] == "identity"
        assert not request.headers.get("authorization")
        assert not request.headers.get("cookie")
        return httpx2.Response(status, headers=headers, stream=Stream())

    monkeypatch.setattr(reference, "MAX_BYTES", 10)
    monkeypatch.setattr(
        reference, "PinnedTransport", lambda base, resolver, **kwargs: httpx2.MockTransport(handler)
    )
    if accepted:
        assert await reference.fetch_catalog(Settings(_env_file=None)) == payload
    else:
        with pytest.raises(ValueError):
            await reference.fetch_catalog(Settings(_env_file=None))
    assert len(requests) == 1


async def test_stream_limit_is_per_transport_and_preserves_default():
    class Stream(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b"x" * 4_000_001

    with pytest.raises(HTTPException):
        async for _ in LimitedStream(Stream()):
            pass
    sizes = [len(chunk) async for chunk in LimitedStream(Stream(), reference.MAX_BYTES)]
    assert sizes == [4_000_001]


async def test_reference_admin_auth_search_no_writes(env, monkeypatch):
    fetch = AsyncMock(return_value=json.dumps(PUBLIC).encode())
    monkeypatch.setattr(reference, "fetch_catalog", fetch)
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    assert (await member.api.get(PATH)).status_code == 403
    assert not fetch.called
    response = await admin.api.get(PATH, params={"q": "OpenAI example"})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 1
    assert (await admin.api.get(PATH, params={"q": "absent"})).json()["total"] == 0
    assert fetch.await_count == 1
    assert (await admin.api.get(BASE)).json()["total"] == 0
    admin.api.cookies.clear()
    assert (await admin.api.get(PATH)).status_code == 401
    assert (
        await admin.api.get(PATH, headers={"authorization": "Bearer desktop"})
    ).status_code == 401


async def test_reasoning_roundtrip_and_old_client_preserves_extensions(env):
    admin = await env.client()
    row = await create(
        admin,
        capabilities={"reasoning": "supported"},
        reasoning_options=OPTIONS,
        icon_key="openai",
        reference={"provider": "openai", "model_id": "example"},
    )
    assert row["reasoning_options"] == OPTIONS
    path = BASE + "/" + row["id"]
    updated = await admin.api.put(path, json=CONFIG | {"version": 1})
    assert updated.status_code == 200, updated.text
    assert updated.json()["reasoning_options"] == OPTIONS
    assert updated.json()["capabilities"]["reasoning"] == "supported"
    assert updated.json()["icon_key"] == "openai"
    assert updated.json()["reference"] == {
        "provider": "openai",
        "model_id": "example",
        "channel_id": None,
    }
    disabled = await admin.api.put(
        path, json=CONFIG | {"version": 2, "capabilities": {"reasoning": "unsupported"}}
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["reasoning_options"] == []


@pytest.mark.parametrize(
    "extra",
    [
        {"reasoning_options": OPTIONS},
        {"icon": "https://example.test/icon.svg"},
        {"icon": "data:image/webp;base64,bm90LWltYWdl"},
        {
            "reasoning_options": [{"type": "effort", "values": []}],
            "capabilities": {"reasoning": "supported"},
        },
        {
            "reasoning_options": [{"type": "effort", "values": ["high", "high"]}],
            "capabilities": {"reasoning": "supported"},
        },
        {
            "reasoning_options": [{"type": "budget_tokens", "min": 100, "max": 10}],
            "capabilities": {"reasoning": "supported"},
        },
        {
            "reasoning_options": [{"type": "toggle"}, {"type": "toggle"}],
            "capabilities": {"reasoning": "supported"},
        },
    ],
)
async def test_invalid_reasoning_and_icons_do_not_save(env, extra):
    admin = await env.client()
    assert (await admin.api.post(BASE, json=CONFIG | extra)).status_code == 422
    assert (await admin.api.get(BASE)).json()["total"] == 0
