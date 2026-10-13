"""Routing behavior through real HTTP, isolated PostgreSQL and native authorization."""

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
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import ModelCall
from app.modules.members.models import Membership

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/models/"


def upstream():
    app = FastAPI()
    state = {"calls": [], "statuses": {}, "entered": None, "release": None}

    @app.post("/{channel}/embeddings")
    async def embeddings(channel: str, request: Request):
        body = await request.json()
        state["calls"].append(channel)
        if state["entered"] and channel == "a":
            state["entered"].set()
            await asyncio.wait_for(state["release"].wait(), 10)
        status = state["statuses"].get(channel, 200)
        if status != 200:
            return JSONResponse(
                {"secret": "never expose upstream error"}, status, headers={"retry-after": "5"}
            )
        return {
            "data": [
                {"index": i, "embedding": [0.1, 0.2, 0.3]} for i, _ in enumerate(body["input"])
            ],
            "usage": {"prompt_tokens": 10},
        }

    @app.post("/{channel}/rerank")
    async def rerank(channel: str, request: Request):
        body = await request.json()
        state["calls"].append(channel)
        status = state["statuses"].get(channel, 200)
        if status != 200:
            return JSONResponse({}, status)
        return {
            "results": [
                {"index": i, "relevance_score": 1 / (i + 1)}
                for i in range(body.get("top_n", len(body["documents"])))
            ],
            "meta": {"billed_units": {"search_units": 2}},
        }

    return app, state


async def setup(env, admin, base, *, certify=True, kind="embedding", **policy):
    env.provider.settings.llm_allowed_private_origins = [base]
    channels = [
        await create_channel(
            admin,
            name="channel-" + key,
            base_url=base + "/" + key,
            models=[{"id": "upstream"}],
            declared_apis=["embeddings", "rerank"],
        )
        for key in ("a", "b", "c")
    ]
    model = await create_model(
        admin,
        kind=kind,
        slug="routed-" + kind,
        retrieval={"dimensions": 3, "embedding_space": "same-weights-preprocess-normalize-v1"},
        routing={"mode": "auto", "fallback": True, **policy},
        access={"audience": "organization"},
        bindings=[
            {
                "channel_id": ch["id"],
                "upstream_id": "upstream",
                "enabled": True,
                "priority": 10 if i < 2 else 0,
                "weight": 100,
                "compatibility_key": "same-weights-preprocess-normalize-v1",
                "price": {"currency": "USD", "input": "1"},
            }
            for i, ch in enumerate(channels)
        ],
    )
    if certify:
        for ch in channels:
            r = await call(admin, model, channel=ch)
            assert r.status_code == 200, r.text
    return model, channels


async def call(admin, model, channel=None):
    params = {"channel_id": channel["id"], "upstream_id": "upstream"} if channel else None
    return await admin.api.post(
        BASE
        + model["id"]
        + ("/test/embeddings" if model["kind"] == "embedding" else "/test/rerank"),
        params=params,
        json={
            "model": model["slug"],
            **(
                {"input": ["sensitive-input"]}
                if model["kind"] == "embedding"
                else {"query": "query", "documents": ["first", "second"], "top_n": 1}
            ),
        },
    )


async def update(admin, model, **changes):
    body = {k: v for k, v in model.items() if k in CatalogInput.model_fields or k == "version"}
    r = await admin.api.put(BASE + model["id"], json=body | changes)
    assert r.status_code == 200, r.text
    return r.json()


async def logs(admin, model):
    return (await admin.api.get(BASE + model["id"] + "/calls")).json()


@pytest.fixture(autouse=True)
def deterministic_sdk_selection(monkeypatch):
    # Choose the first member of an equal-priority tier; priority/failover still
    # runs through the actual SDK, not the removed platform random selector.
    import random

    monkeypatch.setattr(random, "choices", lambda population, **kwargs: [population[0]])
    monkeypatch.setattr(random, "choice", lambda population: population[0])


async def test_sdk_priority_fallback_attempt_costs_and_secret_redaction(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base)
        state["calls"].clear()
        state["statuses"] = {"a": 503, "b": 429}
        response = await call(admin, model)
        assert response.status_code == 200, response.text
        # LiteLLM order fallback moves to the next priority tier. Equal-tier
        # weighting is selection, not Actvero's former sequential retry loop.
        assert state["calls"] == ["a", "c"]
        history = (await logs(admin, model))[0]
        assert [a["upstream_status"] for a in history["attempts"]] == [503, 200]
        assert history["attempts"][0]["estimates"]["procurement"]["status"] == "usage_unknown"
        assert history["attempts"][1]["estimates"]["procurement"]["amount"] == "0.00001"
        assert "sensitive-input" not in str(history) and "never expose" not in str(history)
        assert len({a["attempt_id"] for a in history["attempts"]}) == 2


@pytest.mark.parametrize("status", [400, 422, 401, 403, 429, 503])
async def test_http_failure_policy_belongs_to_sdk(env, status):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base)
        state["calls"].clear()
        state["statuses"] = {"a": status}
        result = await call(admin, model)
        assert result.status_code == 200, result.text
        assert state["calls"] == ["a", "c"]
        history = (await logs(admin, model))[0]
        assert [a["upstream_status"] for a in history["attempts"]] == [status, 200]
        # The old database health projection cannot blacklist the model.
        health = (await admin.api.get(BASE + model["id"] + "/routes")).json()[0]
        assert health["state"] == "ready" and health["failures"] == 0


async def test_optional_diagnostics_and_explicit_business_bindings(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, channels = await setup(env, admin, base, certify=False)
        assert (await call(admin, model)).status_code == 200
        model = await update(admin, model, access={"enabled": True, "audience": "organization"})
        model = await update(admin, model, retrieval={**model["retrieval"], "max_batch_size": 2})
        assert (await call(admin, model)).status_code == 200
        # Embedding-space identity is an explicit data contract, unlike a chat
        # model capability hint or a successful historical diagnostic.
        bindings = [{**b, "compatibility_key": "different-space"} for b in model["bindings"]]
        model = await update(admin, model, bindings=bindings, access={"enabled": False})
        assert (await call(admin, model)).status_code == 409
        bindings = [
            {**b, "enabled": False, "compatibility_key": "same-weights-preprocess-normalize-v1"}
            for b in bindings
        ]
        model = await update(admin, model, bindings=bindings)
        assert (await call(admin, model)).status_code == 409
        assert (await call(admin, model, channels[0])).status_code == 200
        member = await env.client(role="member", tenant=admin.tenant)
        assert (await call(member, model, channels[0])).status_code == 403


@pytest.mark.parametrize("fallback,maximum,expected", [(False, 3, 1), (True, 2, 2), (True, 10, 3)])
async def test_sdk_weighted_failover_is_bounded_and_explicit_test_is_one_send(
    env, fallback, maximum, expected
):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, channels = await setup(env, admin, base, fallback=fallback, max_attempts=maximum)
        model = await update(
            admin, model, bindings=[{**b, "priority": 10} for b in model["bindings"]]
        )
        state["calls"].clear()
        state["statuses"] = {k: 503 for k in "abc"}
        assert (await call(admin, model)).status_code == 502
        assert len(state["calls"]) == expected
        assert len(set(state["calls"])) == expected
        state["calls"].clear()
        assert (await call(admin, model, channels[0])).status_code == 502
        assert state["calls"] == ["a"]


@pytest.mark.parametrize("retry_uncertain,expected", [(False, 1), (True, 2)])
async def test_unknown_timeout_requires_explicit_cost_opt_in(
    env, monkeypatch, retry_uncertain, expected
):
    import httpx
    import httpx2

    from app.modules.llm.providers.sdk_transport import RuntimeTransport

    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base, retry_uncertain=retry_uncertain)
        original = RuntimeTransport.handle_async_request
        attempted = []

        async def timeout(transport, request):
            attempted.append(str(request.url))
            if "/a/" in str(request.url):
                transport.sent = True
                transport.trace.mark_sent()
                transport.failed(httpx2.ReadTimeout("synthetic timeout"))
                raise httpx.ReadTimeout("synthetic timeout")
            return await original(transport, request)

        monkeypatch.setattr(RuntimeTransport, "handle_async_request", timeout)
        result = await call(admin, model)
        assert result.status_code == (200 if retry_uncertain else 504), result.text
        assert len(attempted) == expected
        assert (await logs(admin, model))[0]["attempts"][0]["uncertain"] is True


async def test_sdk_cooldown_and_expiry_use_sdk_cache_not_database_lease(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base, failure_threshold=1)
        state["statuses"] = {"a": 503}
        for _ in range(2):
            assert (await call(admin, model)).status_code == 200
            await asyncio.sleep(0.05)  # SDK's asynchronous observation callbacks.
        gateway = env.app.state.llm_gateway
        cooled = await gateway.router.cooldown_cache.async_get_active_cooldowns(
            list(gateway.router.owned_ids), None
        )
        assert cooled
        state["calls"].clear()
        assert (await call(admin, model)).status_code == 200
        assert "a" not in state["calls"]
        for identity, _ in cooled:
            gateway.router.cooldown_cache.add_deployment_to_cooldown(
                identity, Exception("synthetic"), 503, 0.001
            )
        await asyncio.sleep(0.01)
        state["statuses"], state["calls"] = {}, []
        assert (await call(admin, model)).status_code == 200
        assert state["calls"] == ["a"]


async def test_credential_failure_does_not_poison_another_public_model(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, channels = await setup(env, admin, base)
        second = await create_model(
            admin,
            **{k: v for k, v in model.items() if k in CatalogInput.model_fields}
            | {
                "slug": "second-model",
                "name": "Second",
                "bindings": [
                    {k: v for k, v in b.items() if k != "binding_id"} for b in model["bindings"]
                ],
            },
        )
        state["statuses"] = {"a": 401}
        assert (await call(admin, model)).status_code == 200
        assert (await call(admin, second)).status_code == 200
        state["statuses"] = {}
        assert (await call(admin, second, channels[0])).status_code == 200


async def test_rerank_dispatch_does_not_require_chat_compatibility_certificate(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base, kind="rerank", certify=False)
        model = await update(
            admin, model, bindings=[{**b, "compatibility_key": ""} for b in model["bindings"]]
        )
        state["statuses"], state["calls"] = {"a": 503}, []
        response = await call(admin, model)
        assert response.status_code == 200, response.text
        assert state["calls"] == ["a", "c"]


async def test_native_routing_rechecks_membership_before_fallback(env, monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock(return_value=True))
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base)
        model = await update(
            admin,
            model,
            access={"enabled": True, "audience": "organization"},
            budget_price={"currency": "USD", "input": "1"},
        )
        async with native_client(env) as client:
            tokens, _ = await login(env, monkeypatch, client, admin)
            token = await client.post(
                "/api/v1/desktop/resource-tokens",
                headers=bearer(tokens),
                json={"resource": "llm:" + model["id"]},
            )
            assert token.status_code == 200, token.text
            state["statuses"], state["calls"] = {"a": 503}, []
            state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
            pending = asyncio.create_task(
                client.post(
                    "/api/llm/v1/embeddings",
                    headers=bearer(token.json()),
                    json={"model": model["slug"], "input": ["text"]},
                )
            )
            await asyncio.wait_for(state["entered"].wait(), 5)
            async with env.sessions() as db:
                member = await db.get(Membership, admin.member.id)
                member.status = "removed"
                await db.commit()
            state["release"].set()
            response = await pending
            assert response.status_code in (401, 403)
            assert state["calls"] == ["a"]
            async with env.sessions() as db:
                row = await db.scalar(select(ModelCall).where(ModelCall.source == "desktop"))
                assert len(row.attempts) == 1 and row.termination_code


async def test_cancelled_request_never_falls_back_and_records_unknown(env, monkeypatch):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base, retry_uncertain=True)
        state["calls"] = []
        state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(call(admin, model))
        await asyncio.wait_for(state["entered"].wait(), 5)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        state["release"].set()
        assert state["calls"] == ["a"]
        latest = (await logs(admin, model))[0]
        assert latest["status"] == "unknown" and latest["termination_code"] == "caller_cancelled"
        assert latest["attempts"][0]["uncertain"] is True


async def test_configuration_change_uses_admitted_snapshot(env, monkeypatch):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base)
        state["statuses"], state["calls"] = {"a": 503}, []
        state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(call(admin, model))
        await asyncio.wait_for(state["entered"].wait(), 5)
        await update(admin, model, routing={**model["routing"], "fallback": False})
        state["release"].set()
        assert (await pending).status_code == 200
        assert state["calls"] == ["a", "c"]
        assert (await logs(admin, model))[0]["termination_code"] is None


async def test_total_timeout_bounds_attempt_chain(env, monkeypatch):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await setup(env, admin, base, total_timeout_seconds=3, retry_uncertain=True)
        state["statuses"], state["calls"] = {"a": 503}, []
        state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
        try:
            response = await asyncio.wait_for(call(admin, model), 5)
            assert response.status_code == 504
            assert state["calls"] == ["a"]
            assert (await logs(admin, model))[0]["termination_code"] == "upstream_timeout"
        finally:
            state["release"].set()
