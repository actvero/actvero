"""Channel probes through the actual SDK, loopback providers and isolated tenant data."""

import asyncio
import json
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_mcp import listening

from app.modules.audit.models import AuditEvent
from app.modules.llm.models import (
    CatalogModel,
    ModelCall,
    ModelChannel,
    RouteHealth,
    UsageSettlement,
)

env = identity_env
pytestmark = pytest.mark.asyncio


def probe(operation):
    return {
        "version": 1,
        "id": "opaque-model",
        "operation": operation,
        **(
            {"input": ["private text"], "dimensions": 12}
            if operation == "embedding"
            else {"query": "private query", "documents": ["private text", "other"], "top_n": 1}
        ),
    }


def upstream_for(operation, *, usage=True, status=200, malformed=False):
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def reply(path: str, request: Request):
        body = await request.json()
        calls.append((path, dict(request.headers), body))
        if status != 200:
            return JSONResponse({"error": {"message": "private-key"}}, status_code=status)
        if operation == "embedding":
            return {
                "data": [{"index": True if malformed else 0, "embedding": [0.1] * 12}],
                **({"usage": {"prompt_tokens": 7, "total_tokens": 7}} if usage else {}),
            }
        return {
            "results": [{"index": True if malformed else 1, "relevance_score": 0.9}],
            **({"meta": {"billed_units": {"input_tokens": 9, "search_units": 1}}} if usage else {}),
        }

    return app, calls


async def create(admin, url):
    result = await admin.api.post(
        "/api/v1/llm/channels",
        json={
            "name": "Probe",
            "provider": "openai-compatible",
            "base_url": url + "/custom/v2",
            "api_key": "private-key",
            "models": [{"id": "opaque-model"}],
            "declared_apis": [],
        },
    )
    assert result.status_code == 200, result.text
    return "/api/v1/llm/channels/" + result.json()["id"]


@pytest.mark.parametrize("operation", ["embedding", "rerank"])
@pytest.mark.parametrize("usage", [True, False])
async def test_probe_sdk_results_meters_and_no_publication(env, operation, usage):
    admin = await env.client()
    upstream, calls = upstream_for(operation, usage=usage)
    async with listening(upstream) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        result = await admin.api.post(path + "/test", json=probe(operation))
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["ok"] and data["operation"] == operation
    assert data["usage_source"] == ("upstream" if usage else "unknown")
    assert data["input_tokens"] == ((7 if operation == "embedding" else 9) if usage else None)
    assert len(calls) == 1
    target, headers, body = calls[0]
    assert target == "custom/v2/" + ("embeddings" if operation == "embedding" else "rerank")
    assert headers["authorization"] == "Bearer private-key"
    assert body["model"] == "opaque-model"
    if operation == "embedding":
        assert body["dimensions"] == 12 and body["encoding_format"] == "float"
        assert len(data["vectors"][0]["values"]) == 8 and data["vectors"][0]["dimensions"] == 12
    else:
        assert data["ranks"] == [{"index": 1, "relevance_score": 0.9}]
        assert data["search_units"] == (1 if usage else None)
    history = await admin.api.get(path + "/tests")
    assert history.status_code == 200, history.text
    item = history.json()[0]
    assert item["request_id"] == data["request_id"] and item["status"] == "success"
    assert item["operation"] == operation and not item["stale"]
    assert item["record_version"] == "attempt_v1"
    assert all(item["attempt"][key] == value for key, value in data["attempt"].items())
    assert item["attempt"]["sent"] is True
    assert item["attempt"]["upstream_terminal"] is True
    assert item["attempt"]["client_terminal"] is None
    assert item["input_tokens"] == data["input_tokens"]
    if not usage:
        assert not any(
            evidence["complete"] and evidence["metric"] in ("tokens", "searches")
            for evidence in item["attempt"]["usage_evidence"]
        )
    async with env.sessions() as db:
        row = await db.get(ModelChannel, UUID(path.split("/")[-1]))
        assert row.version == 1 and row.declared_apis == [] and row.checks == []
        assert await db.scalar(select(func.count()).select_from(CatalogModel)) == 0
        assert await db.scalar(select(func.count()).select_from(RouteHealth)) == 0
        assert await db.scalar(select(func.count()).select_from(UsageSettlement)) == 0
        call = await db.get(ModelCall, UUID(data["request_id"]))
        assert call is not None and call.source == "channel_diagnostic"
        assert call.model_id is None and call.status == "succeeded"
        assert call.attempts[0] == item["attempt"]
        assert call.prices == {} and call.estimates == {}
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.action.like("llm.channel.test.%")))
        ).all()
        assert len(events) == 2
        serialized = json.dumps([e.details for e in events])
        assert all(
            word not in serialized
            for word in ["private text", "private query", "private-key", "vectors", "ranks"]
        )
        assert all(
            word not in json.dumps({"attempts": call.attempts, "usage": call.usage})
            for word in ["private text", "private query", "private-key", "vectors", "ranks"]
        )


@pytest.mark.parametrize("operation", ["embedding", "rerank"])
@pytest.mark.parametrize("status,malformed", [(429, False), (200, True)])
async def test_probe_failure_does_not_retry_or_report_estimated_usage(
    env, operation, status, malformed
):
    admin = await env.client()
    upstream, calls = upstream_for(operation, status=status, malformed=malformed)
    async with listening(upstream) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        result = await admin.api.post(path + "/test", json=probe(operation))
    assert result.status_code == 200, result.text
    data = result.json()
    normalized_by_sdk = status == 200 and malformed and operation == "rerank"
    assert data["ok"] is normalized_by_sdk and len(calls) == 1
    assert data["input_tokens"] == (9 if normalized_by_sdk else None)
    if status == 429:
        assert data["attempt"]["retryable_hint"] is True
        assert data["attempt"]["upstream_terminal"] is True
        assert data["attempt"]["error_code"] == "upstream_rate_limited"
    assert "private" not in result.text
    assert (await admin.api.get(path + "/tests")).json()[0]["status"] == (
        "success" if normalized_by_sdk else "failure"
    )


async def test_probe_authorization_validation_and_native_support(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    upstream, calls = upstream_for("embedding")
    async with listening(upstream) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        body = probe("embedding")
        for principal, code in [(member, 403), (outsider, 403)]:
            assert (await principal.api.post(path + "/test", json=body)).status_code == code
            assert (await principal.api.get(path + "/tests")).status_code == code
        assert (
            await admin.api.post(path + "/test", json=body, headers={"x-csrf-token": "bad"})
        ).status_code == 403
        for changed, code in [
            ({"version": 99}, 409),
            ({"id": "absent"}, 422),
            ({"input": [" "]}, 422),
            ({"input": ["x"] * 9}, 422),
            ({"operation": "image"}, 422),
            ({"input": ["x" * 2001]}, 422),
        ]:
            assert (
                await admin.api.post(path + "/test", json={**body, **changed})
            ).status_code == code
        assert (
            await admin.api.post(path + "/test", json={**probe("rerank"), "top_n": 3})
        ).status_code == 422
        native = await admin.api.post(
            "/api/v1/llm/channels",
            json={
                "name": "Native",
                "provider": "gemini",
                "base_url": url,
                "api_key": "private-key",
                "models": [{"id": "opaque-model"}],
            },
        )
        assert native.status_code == 200
        assert (
            await admin.api.post("/api/v1/llm/channels/" + native.json()["id"] + "/test", json=body)
        ).status_code == 422
    assert not calls
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ModelCall)) == 0


async def test_interrupted_diagnostic_survives_as_unconfirmed_history(env):
    admin = await env.client()
    app = FastAPI()
    started, release = asyncio.Event(), asyncio.Event()

    @app.post("/{path:path}")
    async def reply(path: str):
        started.set()
        await release.wait()
        return {"data": [{"index": 0, "embedding": [0.1] * 12}]}

    async with listening(app) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        pending = asyncio.create_task(admin.api.post(path + "/test", json=probe("embedding")))
        await asyncio.wait_for(started.wait(), 10)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        release.set()
    record = (await admin.api.get(path + "/tests")).json()[0]
    assert record["status"] == "unconfirmed" and record["uncertain"]
    assert record["input_tokens"] is None
    assert record["record_version"] == "attempt_v1"
    assert record["attempt"]["sent"] is True
    assert record["attempt"]["client_terminal"] is None
    assert record["attempt"]["error_code"] == "caller_cancelled"
    async with env.sessions() as db:
        call = await db.get(ModelCall, UUID(record["request_id"]))
        assert call is not None and call.status == "unknown"
        assert call.attempts[0] == record["attempt"]
        assert await db.scalar(select(func.count()).select_from(RouteHealth)) == 0
        assert await db.scalar(select(func.count()).select_from(UsageSettlement)) == 0
