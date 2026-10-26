"""Automatic settlement gates against real SDK, loopback upstream and isolated PG."""

import asyncio
from copy import deepcopy
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from llm_billing_helpers import billing
from sqlalchemy import select
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model
from test_llm_channels import create as create_channel
from test_mcp import listening

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.models import ModelCall, UsageSettlement

pytestmark = pytest.mark.asyncio
env = identity_env
GATEWAY = "/api/llm/v1"


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


def upstream():
    app = FastAPI()
    state = {"calls": [], "chat_usage": {}, "embedding_usage": {}, "rerank_units": None}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        state["calls"].append(("chat", await request.json()))
        return {
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "local answer"},
                }
            ],
            "usage": state["chat_usage"],
        }

    @app.post("/v1/embeddings")
    async def embedding(request: Request):
        body = await request.json()
        state["calls"].append(("embedding", body))
        return {
            "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
            "usage": state["embedding_usage"],
        }

    @app.post("/v1/rerank")
    async def rerank(request: Request):
        state["calls"].append(("rerank", await request.json()))
        return {
            "results": [{"index": 0, "relevance_score": 0.9}],
            "meta": (
                {"billed_units": {"search_units": state["rerank_units"]}}
                if state["rerank_units"] is not None
                else {}
            ),
        }

    return app, state


async def configured(env, admin, base, kind, price):
    env.provider.settings.llm_allowed_private_origins = [base]
    endpoint = {"chat": "chat_completions", "embedding": "embeddings", "rerank": "rerank"}[kind]
    channel = await create_channel(
        admin,
        base_url=base + "/v1",
        models=[{"id": "upstream"}],
        declared_apis=[endpoint],
    )
    config = (
        {"context_window": 1000, "max_output": 20}
        if kind == "chat"
        else {
            "retrieval": {"dimensions": 3, "embedding_space": "fixture-v1", "max_search_units": 4}
        }
    )
    model = await create_model(
        admin,
        kind=kind,
        slug="metric-" + kind,
        **config,
        budget_price=price,
        bindings=[
            {
                "channel_id": channel["id"],
                "upstream_id": "upstream",
                "enabled": True,
                "price": price,
            }
        ],
        access={
            "enabled": True,
            "audience": "organization",
            "channel_id": channel["id"],
            "upstream_id": "upstream",
        },
    )
    return model


async def evidence(env, model):
    # Read one committed snapshot after asynchronous outbox replay. Two separate
    # SELECTs can straddle its commit and combine old attempts with new billing.
    async with asyncio.timeout(5):
        while True:
            async with env.sessions() as db:
                pair = (
                    await db.execute(
                        select(ModelCall, UsageSettlement)
                        .join(UsageSettlement, UsageSettlement.id == ModelCall.id)
                        .where(ModelCall.model_id == model["id"])
                    )
                ).one_or_none()
                if pair and pair[0].status != "pending" and pair[1].status != "reserved":
                    call, row = pair
                    return (
                        row.status,
                        deepcopy(row.usage),
                        deepcopy(call.usage),
                        deepcopy(call.attempts),
                        row.evidence.get("reason"),
                    )
            await asyncio.sleep(0.02)


@pytest.mark.parametrize("cache_price", ["0", "0.2"])
async def test_chat_member_key_priced_cache_requires_raw_bucket(env, cache_price):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    app, state = upstream()
    state["chat_usage"] = {"prompt_tokens": 10, "completion_tokens": 2}
    async with listening(app) as base:
        price = {"currency": "USD", "input": "1", "output": "1", "cache_read": cache_price}
        model = await configured(env, admin, base, "chat", price)
        key, _ = await create_key(member)
        async with native_client(env) as api:
            result = await api.post(
                GATEWAY + "/chat/completions",
                headers=headers(key),
                json={"model": model["slug"], "messages": [{"role": "user", "content": "hello"}]},
            )
        assert result.status_code == 200, result.text
        assert [kind for kind, _ in state["calls"]] == ["chat"]
        status, settled_usage, call_usage, attempts, reason = await evidence(env, model)
        assert status == "review" and reason == "priced_cache_missing"
        assert settled_usage.get("cache_read_tokens") is None
        assert call_usage["input_tokens"] == 10 and call_usage["output_tokens"] == 2
        assert attempts[0]["sent"] is True and attempts[0]["upstream_terminal"] is True
        fields = {item["field"]: item for item in attempts[0]["usage_evidence"]}
        assert fields["raw_prompt_tokens"]["value"] == 10
        assert fields["raw_completion_tokens"]["value"] == 2
        assert "cache_read_tokens" not in fields


async def test_chat_no_special_cache_rate_settles_without_fabricated_zero(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    app, state = upstream()
    state["chat_usage"] = {"prompt_tokens": 10, "completion_tokens": 2}
    async with listening(app) as base:
        model = await configured(
            env, admin, base, "chat", {"currency": "USD", "input": "1", "output": "1"}
        )
        key, _ = await create_key(member)
        async with native_client(env) as api:
            result = await api.post(
                GATEWAY + "/chat/completions",
                headers=headers(key),
                json={"model": model["slug"], "messages": [{"role": "user", "content": "hello"}]},
            )
        assert result.status_code == 200, result.text
        status, settled_usage, _, attempts, reason = await evidence(env, model)
        assert status == "settled" and reason == "verified_usage"
        assert settled_usage == {"input_tokens": 10, "output_tokens": 2}
        assert not any(
            item["field"] == "cache_read_tokens" for item in attempts[0]["usage_evidence"]
        )


@pytest.mark.parametrize("metric,expected", [("characters", "settled"), ("tokens", "review")])
@pytest.mark.parametrize("deferred", [False, True])
async def test_embedding_character_evidence_vs_missing_raw_tokens(
    env, monkeypatch, metric, expected, deferred
):
    if deferred:
        outbox = env.app.state.llm_outbox
        flush_one = outbox.flush_one

        async def delayed_flush(path):
            await asyncio.sleep(0.3)
            await flush_one(path)

        monkeypatch.setattr(outbox, "flush_one", delayed_flush)
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    app, state = upstream()
    state["embedding_usage"] = {}
    async with listening(app) as base:
        model = await configured(
            env, admin, base, "embedding", {"currency": "USD", "metric": metric, "input": "1"}
        )
        key, _ = await create_key(member)
        async with native_client(env) as api:
            result = await api.post(
                GATEWAY + "/embeddings",
                headers=headers(key),
                json={"model": model["slug"], "input": "abc"},
            )
        assert result.status_code == 200, result.text
        status, settled_usage, _, attempts, reason = await evidence(env, model)
        assert status == expected
        fields = {item["field"]: item for item in attempts[0]["usage_evidence"]}
        assert fields["input_characters"]["value"] == 3
        assert fields["input_characters"]["source"] == "validated_input"
        assert fields["input_characters"]["phase"] == "validated_input"
        if metric == "characters":
            assert settled_usage == {"input_characters": 3} and reason == "verified_usage"
        else:
            assert fields["input_tokens"]["value"] is None
            assert reason == "input_tokens_missing"


@pytest.mark.parametrize("units,expected", [(2, "settled"), (None, "review")])
async def test_rerank_search_units_require_raw_upstream_meter(env, units, expected):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    app, state = upstream()
    state["rerank_units"] = units
    async with listening(app) as base:
        model = await configured(
            env,
            admin,
            base,
            "rerank",
            {"currency": "USD", "metric": "search_units", "input": "1"},
        )
        key, _ = await create_key(member)
        async with native_client(env) as api:
            result = await api.post(
                GATEWAY + "/rerank",
                headers=headers(key),
                json={
                    "model": model["slug"],
                    "query": "q",
                    "documents": ["first", "second"],
                    "top_n": 1,
                },
            )
        assert result.status_code == 200, result.text
        status, settled_usage, _, attempts, reason = await evidence(env, model)
        assert status == expected
        fields = {item["field"]: item for item in attempts[0]["usage_evidence"]}
        if units is None:
            assert fields["search_units"]["value"] is None and reason == "usage_missing"
        else:
            assert settled_usage == {"search_units": units, "input_characters": 12}
            assert reason == "verified_usage"
            async with env.sessions() as db:
                row = await db.scalar(select(UsageSettlement))
                # Observed characters remain available but do not change search-unit billing.
                assert row.amount == Decimal("0.000002")
            assert fields["search_units"]["value"] == units
            assert fields["search_units"]["source"] == "upstream"
