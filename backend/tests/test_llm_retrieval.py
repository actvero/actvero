"""Retrieval against real loopback HTTP and PostgreSQL; no paid cloud requests."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from llm_billing_helpers import billing
from sqlalchemy import select
from test_desktop import bearer, login, native_client
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model
from test_llm_channels import create as create_channel
from test_mcp import listening

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.catalog_schemas import CatalogInput, RetrievalOptions, TokenPrice
from app.modules.llm.inference_schemas import EmbeddingInput
from app.modules.llm.models import ModelCall
from app.modules.llm.providers.retrieval import normalize
from app.modules.llm.runtime import valuation

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/models/"
GATEWAY = "/api/llm/v1"
PRICE = {"currency": "USD", "input": "0.2"}


async def configured(env, admin, base, kind="embedding", enabled=False, **extra):
    env.provider.settings.llm_allowed_private_origins = [base]
    channel = await create_channel(
        admin,
        base_url=base + "/v1",
        models=[{"id": "upstream"}],
        declared_apis=["embeddings", "rerank"],
    )
    model = await create_model(
        admin,
        kind=kind,
        slug="team-" + kind,
        retrieval={"dimensions": 3, "embedding_space": "fixture-v1", "dimension_options": [2, 3]},
        bindings=[
            {
                "channel_id": channel["id"],
                "upstream_id": "upstream",
                "price": PRICE,
                "enabled": True,  # Execution fixture explicitly opens the new binding.
            }
        ],
        budget_price=PRICE,
        access={
            "enabled": enabled,
            "audience": "organization",
            "channel_id": channel["id"],
            "upstream_id": "upstream",
        },
        **extra,
    )
    return model, channel


def upstream():
    app = FastAPI()
    requests = []

    @app.post("/v1/embeddings")
    async def embedding(request: Request):
        data = await request.json()
        requests.append((dict(request.headers), data))
        texts = [data["input"]] if isinstance(data["input"], str) else data["input"]
        return {
            "data": [
                {"index": i, "embedding": [0.5] * data.get("dimensions", 3)}
                for i in reversed(range(len(texts)))
            ],
            "usage": {"prompt_tokens": 10},
            "secret": "test-secret",
        }

    @app.post("/v1/rerank")
    async def rank(request: Request):
        data = await request.json()
        requests.append((dict(request.headers), data))
        return {
            "results": [
                {"index": i, "relevance_score": 1 / (i + 1)}
                for i in range(data.get("top_n", len(data["documents"])))
            ],
            "meta": {"billed_units": {"search_units": 2}, "secret": "test-secret"},
        }

    return app, requests


async def test_real_http_embeddings_and_logs(env):
    admin = await env.client()
    app, requests = upstream()
    async with listening(app) as base:
        model, channel = await configured(env, admin, base)
        payload = {"model": model["slug"], "input": [" first ", "second"], "dimensions": 2}
        r = await admin.api.post(BASE + model["id"] + "/test/embeddings", json=payload)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["model"] == model["slug"] and data["data"][0]["index"] == 0
        assert len(data["data"][0]["embedding"]) == 2 and data["usage"]["prompt_tokens"] == 10
        assert requests[0][1]["model"] == "upstream" and requests[0][1]["input"][0] == " first "
        assert requests[0][0]["authorization"] == "Bearer test-secret"
        assert "secret" not in r.text
        logs = (await admin.api.get(BASE + model["id"] + "/calls")).json()
        assert logs[0]["usage"]["input_tokens"] == 10
        assert logs[0]["estimates"]["procurement"]["amount"] == "0.000002"
        assert not any(
            word in str(logs) for word in (" first ", "'second'", "test-secret", 'embedding": [')
        )
        member = await env.client(role="member")
        assert (
            await member.api.post(BASE + model["id"] + "/test/embeddings", json=payload)
        ).status_code == 403
        assert (await member.api.get(BASE + model["id"] + "/calls")).status_code == 403
        assert (
            await admin.api.post(
                BASE + model["id"] + "/test/embeddings",
                json=payload,
                headers={"x-csrf-token": "bad"},
            )
        ).status_code == 403
        payload["dimensions"] = 4
        assert (
            await admin.api.post(BASE + model["id"] + "/test/embeddings", json=payload)
        ).status_code == 422
        assert len(requests) == 1
        payload.pop("dimensions")
        assert (
            await admin.api.post(BASE + model["id"] + "/test/embeddings", json=payload)
        ).status_code == 200
        assert requests[-1][1]["dimensions"] == model["retrieval"]["dimensions"]


async def test_rerank_native_meter_exact_prices_and_legacy(env):
    admin = await env.client()
    app, requests = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, "rerank")
        change = {
            **model,
            "budget_price": {
                "currency": "CNY",
                "metric": "search_units",
                "unit": 1000,
                "input": "0.003",
            },
        }
        body = {k: v for k, v in change.items() if k in CatalogInput.model_fields or k == "version"}
        r = await admin.api.put(BASE + model["id"], json=body)
        assert r.status_code == 200, r.text
        model = r.json()
        r = await admin.api.post(
            BASE + model["id"] + "/test/rerank",
            json={
                "model": model["slug"],
                "query": "query",
                "documents": ["first", "second"],
                "top_n": 1,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["meta"] == {"billed_units": {"search_units": 2}}
        log = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert log["estimates"]["budget"]["amount"] == "0.000006"
        assert log["estimates"]["procurement"]["status"] == "usage_unknown"
        assert log["usage"]["input_tokens"] is None
        # Legacy chat clients still omit all extension fields.
        chat = await create_model(admin, slug="legacy")
        update = await admin.api.put(
            BASE + chat["id"], json={"name": "Legacy", "slug": "legacy", "version": chat["version"]}
        )
        assert update.status_code == 200 and update.json()["kind"] == "chat"


async def test_native_tokens_scopes_member_revoke_and_space_lock(env, monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    app, requests = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, enabled=True)
        async with native_client(env) as api:
            root, _ = await login(env, monkeypatch, api, member)

            async def token(resource):
                r = await api.post(
                    "/api/v1/desktop/resource-tokens",
                    headers=bearer(root),
                    json={"resource": resource},
                )
                assert r.status_code == 200, r.text
                return r.json()

            catalog = await token("llm:catalog")
            listed = await api.get(GATEWAY + "/models", headers=bearer(catalog))
            assert listed.status_code == 200, listed.text
            item = listed.json()["data"][0]
            assert item["resource"] == "llm:" + model["id"] and "price" not in listed.text
            invocation = await token(item["resource"])
            payload = {"model": model["slug"], "input": "document"}
            for credential in (catalog, root, await token("mcp:catalog")):
                assert (
                    await api.post(
                        GATEWAY + "/embeddings", headers=bearer(credential), json=payload
                    )
                ).status_code in (401, 403)
            assert (
                await api.get(GATEWAY + "/models", headers=bearer(invocation))
            ).status_code == 403
            assert (
                await api.get("/api/v1/llm/models", headers=bearer(invocation))
            ).status_code == 401
            assert (
                await admin.api.post(
                    GATEWAY + "/embeddings", headers=bearer(invocation), json=payload
                )
            ).status_code == 401
            assert (
                await api.post(
                    GATEWAY + "/embeddings",
                    headers={**bearer(invocation), "origin": "https://evil.test"},
                    json=payload,
                )
            ).status_code == 401
            good = await api.post(GATEWAY + "/embeddings", headers=bearer(invocation), json=payload)
            assert good.status_code == 200, good.text
            assert len(requests) == 1
            update = {
                k: v for k, v in model.items() if k in CatalogInput.model_fields or k == "version"
            }
            update["retrieval"]["dimensions"] = 2
            assert (await admin.api.put(BASE + model["id"], json=update)).status_code == 409
            update["retrieval"]["dimensions"] = 3
            update["access"]["audience"] = "administrators"
            r = await admin.api.put(BASE + model["id"], json=update)
            assert r.status_code == 200, r.text
            assert (
                await api.post(GATEWAY + "/embeddings", headers=bearer(invocation), json=payload)
            ).status_code == 404
            assert not (await api.get(GATEWAY + "/models", headers=bearer(catalog))).json()["data"]
            await api.post("/api/v1/desktop/logout", json={"refresh_token": root["refresh_token"]})
            assert (await api.get(GATEWAY + "/models", headers=bearer(catalog))).status_code == 401


async def test_inflight_revoke_keeps_usage_but_discards_result(env):
    admin = await env.client()
    arrived, release = asyncio.Event(), asyncio.Event()
    app = FastAPI()

    @app.post("/v1/embeddings")
    async def call():
        arrived.set()
        await release.wait()
        return {"data": [{"index": 0, "embedding": [1, 2, 3]}], "usage": {"prompt_tokens": 2}}

    async with listening(app) as base:
        model, channel = await configured(env, admin, base)
        pending = asyncio.create_task(
            admin.api.post(
                BASE + model["id"] + "/test/embeddings",
                json={"model": model["slug"], "input": "private"},
            )
        )
        await asyncio.wait_for(arrived.wait(), 5)
        changed = await admin.api.put(
            "/api/v1/llm/channels/" + channel["id"] + "/archive",
            json={"version": channel["version"], "archived": True},
        )
        assert changed.status_code == 200
        release.set()
        assert (await pending).status_code == 403
        logs = (await admin.api.get(BASE + model["id"] + "/calls")).json()
        assert logs[0]["usage"]["input_tokens"] == 2


@pytest.mark.parametrize(
    "response",
    [
        {"data": [{"index": 0, "embedding": [1, 2]}]},
        {"data": [{"index": 0, "embedding": [1, 2, float("nan")]}]},
        {"data": [{"index": True, "embedding": [1, 2, 3]}]},
        {"data": []},
    ],
)
async def test_invalid_upstream_vectors(response):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        normalize(
            response,
            EmbeddingInput(model="m", input="text"),
            RetrievalOptions(dimensions=3),
            "request",
        )
    assert error.value.status_code == 502


async def test_unknown_usage_is_not_free_and_decimal_units():
    body = EmbeddingInput(model="m", input="text")
    _, usage = normalize(
        {"data": [{"index": 0, "embedding": [1]}]}, body, RetrievalOptions(), "request"
    )
    price = TokenPrice(currency="USD", input="0")
    assert valuation(price, usage)["status"] == "usage_unknown"
    assert valuation(price, {"input_tokens": 0})["amount"] == "0"
    p = TokenPrice(currency="USD", metric="characters", unit=1000, input="0.000000001")
    assert valuation(p, {"input_characters": 3})["amount"] == "0.000000000003"


async def test_body_bound_protocol_errors_no_retry(env):
    admin = await env.client()
    hits = []
    app = FastAPI()

    @app.post("/v1/embeddings")
    async def call():
        hits.append(1)
        return JSONResponse({"error": "test-secret"}, status_code=429)

    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        path = BASE + model["id"] + "/test/embeddings"
        r = await admin.api.post(path, json={"model": model["slug"], "input": "x"})
        assert r.status_code == 429 and "test-secret" not in r.text and len(hits) == 1
        assert (
            await admin.api.post(
                path, json={"model": model["slug"], "input": "x", "encoding_format": "base64"}
            )
        ).status_code == 422
        assert (await admin.api.post(path, content=b" " * 2000001)).status_code == 413
        assert len(hits) == 1
        async with env.sessions() as db:
            records = (await db.scalars(select(ModelCall))).all()
            assert len(records) == 1 and records[0].status == "failed"
