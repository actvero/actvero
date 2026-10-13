"""Actual SDK sends, fallback boundaries and concurrent outcomes on isolated PostgreSQL."""

import asyncio
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from test_identity_access import env as identity_env
from test_llm_execution import BASE, configured, payload
from test_llm_routing import update
from test_mcp import listening

from app.modules.llm import routing
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import CatalogModel, ModelCall, ModelChannel, RouteHealth

env = identity_env
pytestmark = pytest.mark.asyncio


def upstream():
    app = FastAPI()
    state = {"calls": [], "status": 200, "code": None, "wait": None, "first": None}

    @app.post("/{channel}/chat/completions")
    async def call(channel: str, request: Request):
        await request.json()
        state["calls"].append(channel)
        status = state["status"] if channel == "a" else 200
        # Capture the response before blocking, so a newer rejection can finish first.
        if state["first"] is not None:
            entered, release = state["first"]
            state["first"] = None
            entered.set()
            await asyncio.wait_for(release.wait(), 15)
        if status != 200:
            return JSONResponse(
                {"error": {"code": state["code"], "message": "private-provider-body"}},
                status,
                headers={"Retry-After": state["wait"]} if state["wait"] is not None else {},
            )
        return {
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "ok",
                    },
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    return app, state


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 503])
async def test_http_failure_fallback_and_wait_are_owned_by_sdk(env, status):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, channels = await configured(env, admin, base, auto=True)
        async with env.sessions() as db:
            first = await db.get(ModelChannel, UUID(channels[0]["id"]))
            first.automatic_protection = {"enabled": False}
            await db.commit()
        state.update(status=status, wait="7200" if status == 429 else None, calls=[])
        result = await admin.api.post(BASE + model["id"] + "/test/chat", json=payload(model))
        assert result.status_code == 200, result.text
        assert state["calls"] == ["a", "b"]
        record = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert len(record["attempts"]) == 2
        assert [a["upstream_status"] for a in record["attempts"]] == [status, 200]
        assert "private-provider-body" not in str(record["attempts"])
        if status == 429:
            async with env.sessions() as db:
                saved = await db.get(ModelCall, UUID(record["id"]))
                assert saved.attempts[0]["retry_after_seconds"] == 7200
        await asyncio.sleep(0.05)
        router = env.app.state.llm_gateway.router
        cooled = await router.cooldown_cache.async_get_active_cooldowns(
            list(router.owned_ids), None
        )
        assert bool(cooled) is (status in {401, 429})
        if status == 429:
            assert cooled[0][1]["cooldown_time"] >= 7200
        state["calls"].clear()
        again = await admin.api.post(BASE + model["id"] + "/test/chat", json=payload(model))
        assert again.status_code == 200, again.text
        assert state["calls"] == (["b"] if cooled else ["a", "b"])
        routes = (await admin.api.get(BASE + model["id"] + "/routes")).json()
        assert all(r["state"] == "ready" for r in routes)  # Business eligibility, not SDK health.


async def test_fixed_binding_http_rejection_does_not_require_test_certificate(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        state.update(status=404, code="model_not_found", calls=[])
        rejected = await admin.api.post(BASE + model["id"] + "/test/chat", json=payload(model))
        assert rejected.status_code == 502
        state["status"] = 200
        recovered = await admin.api.post(BASE + model["id"] + "/test/chat", json=payload(model))
        assert recovered.status_code == 200, recovered.text
        assert state["calls"] == ["a", "a"]


async def test_removed_binding_does_not_pass_old_health_to_new_identity(env):
    admin = await env.client()
    app, _ = upstream()
    async with listening(app) as base:
        model, channels = await configured(env, admin, base, auto=True)
        async with env.sessions() as db:
            row = await db.get(CatalogModel, UUID(model["id"]))
            config = CatalogInput.model_validate(row.configuration).for_operation("chat")
            second = config.bindings[1]
            second_key = routing.health_key(row.tenant_id, row.id, "chat", second)
            first_key = routing.health_key(row.tenant_id, row.id, "chat", config.bindings[0])
            first_channel = await db.get(ModelChannel, config.bindings[0].channel_id)
            first_health = await routing.ensure(
                db,
                row.tenant_id,
                first_key,
                routing.fingerprint(config, config.bindings[0], first_channel),
            )
            first_tested = first_health.tested_at
            channel = await db.get(ModelChannel, second.channel_id)
            credential = await routing.ensure(
                db,
                row.tenant_id,
                routing.credential_key(channel),
                routing.credential_fingerprint(channel),
            )
            credential.blocked = True
            await db.commit()
        old_id = model["bindings"][1]["binding_id"]
        model = await update(admin, model, bindings=[model["bindings"][0]])
        async with env.sessions() as db:
            assert await db.get(RouteHealth, second_key) is None
        model = await update(
            admin,
            model,
            bindings=[
                *model["bindings"],
                {
                    "channel_id": channels[1]["id"],
                    "upstream_id": "vendor-chat",
                    "compatibility_key": "chat-v1",
                },
            ],
        )
        assert model["bindings"][1]["binding_id"] != old_id
        assert model["bindings"][1]["enabled"] is False
        async with env.sessions() as db:
            assert await db.get(RouteHealth, second_key) is None
            assert (await db.get(RouteHealth, first_key)).tested_at == first_tested
            assert (await db.get(RouteHealth, credential.id)).blocked
