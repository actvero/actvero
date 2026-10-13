"""Real LiteLLM retrieval adapters, loopback HTTP and isolated settlement storage."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from llm_billing_helpers import billing
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_execution import entries
from test_llm_retrieval import configured
from test_mcp import listening

from app.core.config import Settings
from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.catalog_schemas import RetrievalOptions
from app.modules.llm.inference_schemas import EmbeddingInput, RerankInput
from app.modules.llm.providers import retrieval
from app.modules.llm.providers.retrieval import UpstreamFailure

env = identity_env
pytestmark = pytest.mark.asyncio


def fixture_provider(kind, *, usage=True, status=200, malformed=False):
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def call(path: str, request: Request):
        body = await request.json()
        calls.append((path, dict(request.headers), body))
        if status != 200:
            return JSONResponse(
                {"error": {"message": "private-provider-secret"}},
                status_code=status,
                headers={"retry-after": "5", "location": "/other"},
            )
        if kind == "embedding":
            result = {"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}
            if usage:
                result["usage"] = {"prompt_tokens": 7, "total_tokens": 7}
            if malformed:
                result["data"][0]["index"] = True
        else:
            result = {"results": [{"index": 0, "relevance_score": 0.8}]}
            if usage:
                # Compatible services may report usage instead of Cohere meta.
                result["usage"] = {"total_tokens": 9}
            if malformed:
                result["results"][0]["index"] = True
        return result

    return app, calls


def request_for(kind):
    return (
        EmbeddingInput(model="team-embedding", input="private input", dimensions=3)
        if kind == "embedding"
        else RerankInput(model="team-rerank", query="private query", documents=["private input"])
    )


async def invoke(kind, base, *, key="test-key", timeout=5, settings=None):
    limits = RetrievalOptions(dimensions=3, dimension_options=[3])
    body = request_for(kind)
    path, payload, _ = retrieval.prepare(body, limits, "custom/model-name")
    raw = await retrieval.post(
        base,
        path,
        key,
        timeout,
        settings or Settings(_env_file=None, llm_allowed_private_origins=[base]),
        payload,
    )
    return retrieval.normalize(raw, body, limits, "test-request")


@pytest.mark.parametrize("kind", ["embedding", "rerank"])
@pytest.mark.parametrize("prefix", ["", "/v1", "/tenant/custom/v2"])
async def test_configured_prefix_model_parameters_and_auth(kind, prefix):
    app, calls = fixture_provider(kind)
    async with listening(app) as base:
        output, usage = await invoke(kind, base + prefix)
    assert len(calls) == 1
    path, request_headers, body = calls[0]
    assert path == prefix.lstrip("/") + ("/" if prefix else "") + (
        "embeddings" if kind == "embedding" else "rerank"
    )
    assert request_headers["authorization"] == "Bearer test-key"
    assert body["model"] == "custom/model-name"
    assert usage["source"] == "upstream"
    assert usage["input_tokens"] == (7 if kind == "embedding" else 9)
    if kind == "embedding":
        assert body["dimensions"] == 3 and body["encoding_format"] == "float"
        assert output.data[0].embedding == [0.1, 0.2, 0.3]
    else:
        assert body["return_documents"] is False
        assert output.results[0].relevance_score == 0.8


@pytest.mark.parametrize("kind", ["embedding", "rerank"])
async def test_missing_usage_remains_unknown_and_no_auth_stays_anonymous(kind):
    app, calls = fixture_provider(kind, usage=False)
    async with listening(app) as base:
        _, usage = await invoke(kind, base + "/v1", key=None)
    assert usage["source"] == "unknown" and usage["input_tokens"] is None
    assert "authorization" not in calls[0][1]


@pytest.mark.parametrize("kind", ["embedding", "rerank"])
async def test_sdk_coercion_does_not_accept_invalid_original_indices(kind):
    app, calls = fixture_provider(kind, malformed=True)
    async with listening(app) as base:
        with pytest.raises(HTTPException) as error:
            await invoke(kind, base + "/v1")
    assert error.value.status_code == 502
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["embedding", "rerank"])
@pytest.mark.parametrize("status", [401, 429, 503, 307])
async def test_errors_are_sanitized_without_sdk_retry_or_redirect(kind, status):
    app, calls = fixture_provider(kind, status=status)
    async with listening(app) as base:
        with pytest.raises(UpstreamFailure) as error:
            await invoke(kind, base + "/v1")
    assert len(calls) == 1
    assert error.value.upstream_status == status
    assert error.value.retryable is (status != 307)
    assert "private-provider-secret" not in str(error.value.detail)
    if status == 429:
        assert error.value.retry_after == 5


@pytest.mark.parametrize("kind", ["embedding", "rerank"])
async def test_denied_private_destination_never_reaches_provider(kind):
    app, calls = fixture_provider(kind)
    async with listening(app) as base:
        with pytest.raises(HTTPException) as error:
            await invoke(kind, base + "/v1", settings=Settings(_env_file=None))
    assert error.value.status_code == 422
    assert calls == []


async def test_concurrent_credentials_do_not_share_clients():
    app, calls = fixture_provider("embedding")
    async with listening(app) as base:
        await asyncio.gather(
            invoke("embedding", base + "/account-a/v1", key="key-a"),
            invoke("embedding", base + "/account-b/v1", key="key-b"),
        )
    assert {path: h["authorization"] for path, h, _ in calls} == {
        "account-a/v1/embeddings": "Bearer key-a",
        "account-b/v1/embeddings": "Bearer key-b",
    }


@pytest.mark.parametrize("kind", ["embedding", "rerank"])
async def test_cancelled_calls_send_once_and_propagate(kind):
    app, arrived, release, calls = FastAPI(), asyncio.Event(), asyncio.Event(), []

    @app.post("/{path:path}")
    async def call(path: str):
        calls.append(path)
        arrived.set()
        await release.wait()
        return {}

    async with listening(app) as base:
        pending = asyncio.create_task(invoke(kind, base + "/v1"))
        try:
            await asyncio.wait_for(arrived.wait(), 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            release.set()
    assert len(calls) == 1


@pytest.mark.parametrize("kind", ["embedding", "rerank"])
async def test_member_missing_usage_retains_hold_for_review(env, monkeypatch, kind):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    app, calls = fixture_provider(kind, usage=False)
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, kind=kind, enabled=True)
        key, _ = await create_key(member)
        async with native_client(env) as api:
            response = await api.post(
                "/api/llm/v1/" + ("embeddings" if kind == "embedding" else "rerank"),
                json=request_for(kind).model_dump(exclude_none=True),
                headers=headers(key),
            )
        assert response.status_code == 200, response.text
        row = (await entries(admin))[0]
        assert row["status"] == "review" and row["points"] is None
        assert Decimal(row["reserved_points"]) > 0
        assert len(calls) == 1
        assert "private input" not in str(row)
        assert model["access"]["enabled"] is True
