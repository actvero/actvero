"""Runtime attempt evidence against one local SDK upstream and isolated PostgreSQL."""

import asyncio
import json
from uuid import UUID

import pytest
from sqlalchemy import select
from test_identity_access import env as identity_env
from test_image_gateway import configure as configure_image
from test_image_gateway import upstream as image_upstream
from test_llm_execution import BASE, configured, payload, upstream
from test_llm_retrieval import configured as configure_retrieval
from test_llm_retrieval import upstream as retrieval_upstream
from test_llm_routing import update
from test_mcp import listening

from app.modules.llm.models import ModelCall

env = identity_env
pytestmark = pytest.mark.asyncio


async def stored(env, model_id: str) -> ModelCall:
    async with env.sessions() as db:
        row = await db.scalar(select(ModelCall).where(ModelCall.model_id == UUID(model_id)))
        assert row is not None
        return row


async def test_pending_snapshot_commits_before_dispatch_then_records_real_terminal(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
        request = asyncio.create_task(
            admin.api.post(BASE + model["id"] + "/test/chat", json=payload(model))
        )
        try:
            await asyncio.wait_for(state["entered"].wait(), 10)
            admitted = await stored(env, model["id"])
            assert admitted.status == "pending" and admitted.attempts == []
            event = json.loads(
                (env.app.state.llm_outbox.directory / (str(admitted.id) + ".json")).read_text()
            )
            pending = event["attempts"][0]
            UUID(pending["attempt_id"])
            assert pending["status"] == "pending" and pending["sent"] is None
            assert pending["binding_id"] and pending["operation"] == "chat"
            assert pending["config_version"] == model["version"]
            assert pending["client_terminal"] is None
            assert "private prompt" not in json.dumps(pending)
        finally:
            state["release"].set()
        response = await request
        assert response.status_code == 200, response.text
        done = (await stored(env, model["id"])).attempts[0]
        assert done["attempt_id"] == pending["attempt_id"]
        assert done["status"] == "succeeded"
        assert done["sent"] is True and done["upstream_terminal"] is True
        assert done["output_started"] is True and done["client_terminal"] is None
        assert 0 <= done["first_output_ms"] <= done["duration_ms"]
        assert any(
            entry["field"] == "input_tokens"
            and entry["source"] == "upstream"
            and entry["value"] is not None
            for entry in done["usage_evidence"]
        )


async def test_broken_stream_keeps_output_start_but_no_terminal(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        state["broken"] = True
        response = await admin.api.post(
            BASE + model["id"] + "/test/chat", json=payload(model, stream=True)
        )
        assert response.status_code == 200, response.text
        assert '"error"' not in response.text and "[DONE]" in response.text
        attempt = (await stored(env, model["id"])).attempts[0]
        assert attempt["status"] == "succeeded" and attempt["uncertain"]
        assert attempt["sent"] is True and attempt["output_started"] is True
        assert attempt["upstream_terminal"] is False
        assert attempt["client_terminal"] is None


async def test_missing_upstream_usage_is_not_recorded_as_free(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        state["usage"] = None
        response = await admin.api.post(BASE + model["id"] + "/test/chat", json=payload(model))
        assert response.status_code == 200, response.text
        attempt = (await stored(env, model["id"])).attempts[0]
        assert attempt["sent"] is True and attempt["upstream_terminal"] is True
        assert not any(
            entry["field"].endswith("tokens")
            and entry["source"] == "upstream"
            and entry["value"] == 0
            for entry in attempt["usage_evidence"]
        )


@pytest.mark.parametrize("stream", [False, True])
async def test_chat_omitted_cache_fields_do_not_become_upstream_zero_evidence(env, stream):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        state["usage"] = {"prompt_tokens": 100, "completion_tokens": 10}
        response = await admin.api.post(
            BASE + model["id"] + "/test/chat", json=payload(model, stream=stream)
        )
        assert response.status_code == 200, response.text
        evidence = (await stored(env, model["id"])).attempts[0]["usage_evidence"]
        assert any(
            item["field"] == "input_tokens" and item["source"] == "upstream" for item in evidence
        )
        assert not any(item["field"].startswith("cache_") for item in evidence)


async def test_cancelled_stream_persists_actual_dispatch_without_client_terminal(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        state["after_first"], state["continue_stream"] = asyncio.Event(), asyncio.Event()
        pending = asyncio.create_task(
            admin.api.post(BASE + model["id"] + "/test/chat", json=payload(model, stream=True))
        )
        try:
            await asyncio.wait_for(state["after_first"].wait(), 10)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            async with asyncio.timeout(5):
                while (row := await stored(env, model["id"])).status == "pending":
                    await asyncio.sleep(0.02)
            attempt = row.attempts[0]
            assert attempt["status"] == "unknown"
            assert attempt["sent"] is True and attempt["upstream_terminal"] is False
            assert attempt["client_terminal"] is None
            assert attempt["error_code"] == "caller_cancelled"
            assert attempt["certainly_unused"] is False
        finally:
            state["continue_stream"].set()


async def test_timeout_keeps_dispatched_attempt_uncertain(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        model = await update(admin, model, routing={**model["routing"], "total_timeout_seconds": 3})
        state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
        try:
            response = await admin.api.post(BASE + model["id"] + "/test/chat", json=payload(model))
            assert response.status_code == 504, response.text
            attempt = (await stored(env, model["id"])).attempts[0]
            assert attempt["status"] == "failed"
            assert attempt["sent"] is True and attempt["upstream_terminal"] is False
            assert attempt["client_terminal"] is None
            assert attempt["uncertain"] is True and attempt["certainly_unused"] is False
        finally:
            state["release"].set()


async def test_retrieval_character_evidence_is_validated_input_not_provider_meter(env):
    admin = await env.client()
    app, _ = retrieval_upstream()
    async with listening(app) as base:
        model, _ = await configure_retrieval(env, admin, base)
        response = await admin.api.post(
            BASE + model["id"] + "/test/embeddings",
            json={"model": model["slug"], "input": ["abc", "de"], "dimensions": 2},
        )
        assert response.status_code == 200, response.text
        attempt = (await stored(env, model["id"])).attempts[0]
        assert any(
            item["field"] == "input_characters"
            and item["value"] == 5
            and item["source"] == "validated_input"
            for item in attempt["usage_evidence"]
        )
        assert any(
            item["field"] == "input_tokens" and item["value"] == 10 and item["source"] == "upstream"
            for item in attempt["usage_evidence"]
        )


async def test_image_count_evidence_requires_confirmed_delivery(env):
    admin = await env.client()
    app, _ = image_upstream()
    async with listening(app) as base:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure_image(admin, base)
        response = await admin.api.post(
            BASE + model["id"] + "/test/images",
            json={"model": model["slug"], "prompt": "fixture prompt"},
        )
        assert response.status_code == 200, response.text
        attempt = (await stored(env, model["id"])).attempts[0]
        assert any(
            item["field"] == "image_count"
            and item["value"] == 1
            and item["source"] == "confirmed_delivery"
            for item in attempt["usage_evidence"]
        )
        assert "fixture prompt" not in json.dumps(attempt)
