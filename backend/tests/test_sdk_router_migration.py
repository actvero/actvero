"""Real Router dispatch, isolation and accounting recovery (no paid upstreams)."""

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest
from llm_billing_helpers import billing
from sqlalchemy import select
from test_desktop import bearer, native_client
from test_identity_access import env as identity_env
from test_llm_execution import BASE, GATEWAY, configured, credentials, entries, payload, upstream
from test_llm_routing import update
from test_mcp import listening

from app.modules.llm.accounting_outbox import Outbox
from app.modules.llm.models import RouteHealth
from app.modules.llm.providers.sdk import litellm
from app.modules.llm.providers.sdk_router import Gateway

env = identity_env
pytestmark = pytest.mark.asyncio


async def test_sdk_dispatch_ignores_legacy_circuit_and_test_certificates(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, auto=True)
        model = await update(
            admin, model, bindings=[{**b, "compatibility_key": ""} for b in model["bindings"]]
        )
        async with env.sessions() as db:
            for row in await db.scalars(select(RouteHealth)):
                row.blocked = True
                row.failures = 100
            await db.commit()
        state["calls"].clear()
        state["statuses"] = {"a": 503}
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
        assert result.status_code == 200, result.text
        assert [c[0] for c in state["calls"]] == ["a", "b"]
        history = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert [a["upstream_status"] for a in history["attempts"]] == [503, 200]
        assert len({a["attempt_id"] for a in history["attempts"]}) == 2


async def test_configuration_edit_does_not_withhold_admitted_response_or_change_price(
    env, monkeypatch
):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        state.update(entered=asyncio.Event(), release=asyncio.Event())
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            task = asyncio.create_task(
                api.post(GATEWAY, headers=bearer(token), json=payload(model))
            )
            try:
                await asyncio.wait_for(state["entered"].wait(), 5)
                await update(
                    admin,
                    model,
                    name="renamed while generating",
                    budget_price={**model["budget_price"], "input": "99"},
                )
            finally:
                state["release"].set()
            result = await task
        assert result.status_code == 200, result.text
        entry = (await entries(admin))[0]
        assert entry["status"] == "settled" and entry["points"] == "0.0244"


async def test_database_write_outage_delivers_and_replay_settles_once(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        outbox = env.app.state.llm_outbox
        original = outbox.flush_one

        async def unavailable(_path):
            raise ConnectionError("simulated accounting database outage")

        monkeypatch.setattr(outbox, "flush_one", unavailable)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
        assert result.status_code == 200, result.text
        files = list(outbox.directory.glob("*.json"))
        assert len(files) == 1
        event = json.loads(files[0].read_text())
        assert event["complete"] and event["delivered"]
        assert "private prompt" not in files[0].read_text()
        assert (await entries(admin))[0]["status"] == "reserved"
        monkeypatch.setattr(outbox, "flush_one", original)
        # A fresh consumer represents process restart; duplicate delivery must
        # not overwrite either automatic or later manual settlement.
        restarted = Outbox(outbox.directory, env.app.state.database)
        await restarted.flush_one(files[0])
        restarted.write(event)
        await restarted.flush_one(files[0])
        entry = (await entries(admin))[0]
        assert entry["status"] == "settled" and entry["points"] == "0.0244"
        assert len(state["calls"]) == 1
        assert not list(outbox.directory.glob("*.json"))


async def test_expired_dispatch_intent_becomes_review_without_reissuing_model(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        outbox = env.app.state.llm_outbox
        original = outbox.flush_one
        monkeypatch.setattr(outbox, "flush_one", AsyncMock(side_effect=ConnectionError()))
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
        assert result.status_code == 200
        path = next(outbox.directory.glob("*.json"))
        event = json.loads(path.read_text())
        event.update(complete=False, expires_at=time.time() - 1, usage={})
        event["attempts"][-1].update(
            status="pending",
            sent=None,
            upstream_terminal=False,
            usage={},
            usage_evidence=[],
            uncertain=True,
        )
        outbox.write(event)
        monkeypatch.setattr(outbox, "flush_one", original)
        await original(path)
        entry = (await entries(admin))[0]
        assert entry["status"] == "review" and entry["points"] is None
        assert len(state["calls"]) == 1


async def test_router_callbacks_are_owned_and_discard_keeps_foreign_callbacks(env):
    def sentinel(*args):
        return None

    litellm.success_callback.append(sentinel)
    gateway = Gateway(env.provider.settings)
    router = gateway.router
    before = dict(router.cache.in_memory_cache.cache_dict)
    unrelated = {
        "litellm_params": {"metadata": {"model_group": "foreign"}, "model_info": {"id": "foreign"}}
    }
    router.sync_deployment_callback_on_success(unrelated, None, None, None)
    router.deployment_callback_on_failure(unrelated, None, None, None)
    assert dict(router.cache.in_memory_cache.cache_dict) == before
    gateway.close()
    assert sentinel in litellm.success_callback
    assert not any(getattr(c, "__self__", None) is router for c in litellm.success_callback)
    assert not any(getattr(c, "__self__", None) is router for c in litellm.failure_callback)
    litellm.success_callback.remove(sentinel)


async def test_router_rejection_before_dispatch_releases_reservation(env, monkeypatch):
    from litellm.exceptions import RateLimitError

    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        gateway = Gateway(env.provider.settings)
        env.app.state.llm_gateway = gateway
        monkeypatch.setattr(
            gateway.router,
            "acompletion",
            AsyncMock(
                side_effect=RateLimitError(
                    "synthetic SDK cooldown", model="public", llm_provider="openai"
                )
            ),
        )
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
        assert result.status_code == 429, result.text
        assert state["calls"] == []
        entry = (await entries(admin))[0]
        assert entry["status"] == "released" and entry["points"] == "0"


async def test_late_disk_failure_preserves_answer_and_unknown_charge(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        outbox = env.app.state.llm_outbox
        original = outbox.write

        def fail_final(record):
            if record["complete"]:
                raise OSError("synthetic disk full")
            original(record)

        monkeypatch.setattr(outbox, "write", fail_final)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
        assert result.status_code == 200, result.text
        entry = (await entries(admin))[0]
        assert entry["status"] == "reserved"
        path = next(outbox.directory.glob("*.json"))
        event = json.loads(path.read_text())
        assert event["complete"] is False and event["attempts"]
        event["expires_at"] = time.time() - 1
        original(event)
        await outbox.flush_one(path)
        assert (await entries(admin))[0]["status"] == "review"
        assert len(state["calls"]) == 1


async def test_concurrent_authorized_pools_do_not_share_model_or_credentials(env, monkeypatch):
    from uuid import UUID

    from test_repository_isolation import organizations

    from app.modules.llm.models import ModelChannel

    admin, other = await organizations(env)
    app_a, state_a = upstream()
    app_b, state_b = upstream()

    @app_a.middleware("http")
    async def capture_a(request, call_next):
        state_a["authorization"] = request.headers.get("authorization")
        return await call_next(request)

    @app_b.middleware("http")
    async def capture_b(request, call_next):
        state_b["authorization"] = request.headers.get("authorization")
        return await call_next(request)

    async with listening(app_a) as a, listening(app_b) as b:
        first, _ = await configured(env, admin, a)
        second, _ = await configured(env, other, b)
        async with env.sessions() as db:
            for model, key in [(first, "synthetic-tenant-a"), (second, "synthetic-tenant-b")]:
                channel = await db.get(ModelChannel, UUID(model["access"]["channel_id"]))
                channel.auth_mode = "api_key"
                channel.sealed_key = env.provider.seal({"key": key})
            await db.commit()
        env.provider.settings.llm_allowed_private_origins = [a, b]
        for state in (state_a, state_b):
            state.update(entered=asyncio.Event(), release=asyncio.Event())

        async def run(client, model):
            return await client.api.post(BASE + model["id"] + "/test/chat", json=payload(model))

        tasks = [asyncio.create_task(run(admin, first)), asyncio.create_task(run(other, second))]
        try:
            await asyncio.wait_for(
                asyncio.gather(state_a["entered"].wait(), state_b["entered"].wait()), 5
            )
        finally:
            state_a["release"].set()
            state_b["release"].set()
        results = await asyncio.gather(*tasks)
        assert all(r.status_code == 200 for r in results), [r.text for r in results]
        assert len(state_a["calls"]) == len(state_b["calls"]) == 1
        assert state_a["authorization"] == "Bearer synthetic-tenant-a"
        assert state_b["authorization"] == "Bearer synthetic-tenant-b"
        first_logs = (await admin.api.get(BASE + first["id"] + "/calls")).json()
        second_logs = (await other.api.get(BASE + second["id"] + "/calls")).json()
        assert len(first_logs) == len(second_logs) == 1
        assert (
            first_logs[0]["attempts"][0]["channel_id"]
            != second_logs[0]["attempts"][0]["channel_id"]
        )
        assert (await admin.api.get(BASE + second["id"] + "/calls")).status_code == 404


async def test_fallback_uses_selected_binding_parameters_without_previous_dialect(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, auto=True)
        bindings = model["bindings"]
        bindings[0]["chat_options"].update(
            reasoning_format="enable_thinking", output_parameter="max_tokens"
        )
        bindings[1]["chat_options"].update(
            reasoning_format="openai", output_parameter="max_completion_tokens"
        )
        model = await update(admin, model, bindings=bindings)
        state.update(statuses={"a": 503}, calls=[])
        result = await admin.api.post(
            BASE + model["id"] + "/test/chat",
            json=payload(model, thinking={"type": "disabled"}),
        )
        assert result.status_code == 200, result.text
        first, second = [body for _, body in state["calls"]]
        assert first["enable_thinking"] is False and first["max_tokens"] == 100
        assert "enable_thinking" not in second and "max_tokens" not in second
        assert second["reasoning_effort"] == "none" and second["max_completion_tokens"] == 100


@pytest.mark.parametrize("stream", [False, True])
async def test_live_permission_database_outage_keeps_admitted_delivery(env, monkeypatch, stream):
    from app.modules.llm import runtime

    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        check = AsyncMock(side_effect=ConnectionError("synthetic post-admission database outage"))
        monkeypatch.setattr(runtime, "check_live", check)
        response = await admin.api.post(
            BASE + model["id"] + "/test/chat", json=payload(model, stream=stream)
        )
        assert response.status_code == 200 and '"error"' not in response.text, response.text
        assert "[DONE]" in response.text if stream else response.json()["choices"]
        assert check.await_count >= 2 and len(state["calls"]) == 1


async def test_outbox_tightens_existing_volume_directory_permissions(tmp_path):
    directory = tmp_path / "existing-volume"
    directory.mkdir(mode=0o755)
    Outbox(directory, None)
    assert directory.stat().st_mode & 0o777 == 0o700
