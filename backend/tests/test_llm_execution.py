"""Chat and monetary admission against real PostgreSQL and loopback upstream HTTP."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from llm_billing_helpers import billing
from sqlalchemy import select
from test_desktop import bearer, login, native_client
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model
from test_llm_channels import create as create_channel
from test_llm_routing import update
from test_mcp import listening
from test_quota_policies import edit, hours, week

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm import settlement
from app.modules.llm.models import QuotaClock, UsageSettlement

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/models/"
GATEWAY = "/api/llm/v1/chat/completions"
PRICE = {"currency": "USD", "input": "2", "output": "8", "cache_read": "0.2"}
METER = {
    "prompt_tokens": 100,
    "completion_tokens": 10,
    "prompt_tokens_details": {"cached_tokens": 20},
}


def upstream():
    app = FastAPI()
    state = {
        "calls": [],
        "statuses": {},
        "usage": METER,
        "broken": False,
        "entered": None,
        "release": None,
        "tools": False,
        "tool_continuation_id": None,
        "after_first": None,
        "continue_stream": None,
    }

    @app.post("/{channel}/chat/completions")
    async def call(channel: str, request: Request):
        body = await request.json()
        state["calls"].append((channel, body))
        if state["entered"]:
            state["entered"].set()
            await asyncio.wait_for(state["release"].wait(), 10)
        status = state["statuses"].get(channel, 200)
        if status != 200:
            return JSONResponse({"secret": "upstream private detail"}, status)
        if not body.get("stream"):
            return {
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": "answer",
                            "reasoning_content": "reason",
                        },
                    }
                ],
                "usage": state["usage"],
            }

        def event(delta, finish=None):
            return (
                "data: "
                + json.dumps({"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})
                + "\n\n"
            )

        async def events():
            yield event({"role": "assistant"})
            if state["after_first"]:
                state["after_first"].set()
                await asyncio.wait_for(state["continue_stream"].wait(), 10)
            yield event({"reasoning_content": "reason"})
            if state["broken"]:
                yield event({"content": "partial"})
                return
            if state["tools"]:
                yield event(
                    {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "lookup", "arguments": '{"q":'},
                            }
                        ]
                    }
                )
                continuation = {"index": 0, "function": {"arguments": '"ok"}'}}
                if state["tool_continuation_id"] is not None:
                    continuation["id"] = state["tool_continuation_id"]
                yield event({"tool_calls": [continuation]})
                yield event({}, "tool_calls")
            else:
                yield event({"content": "answer"})
                yield event({}, "stop")
            yield "data: " + json.dumps({"choices": [], "usage": state["usage"]}) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app, state


async def configured(env, admin, base, auto=False):
    env.provider.settings.llm_allowed_private_origins = [base]
    channels = [
        await create_channel(
            admin,
            name="chat-" + k,
            base_url=base + "/" + k,
            models=[{"id": "vendor-chat"}],
            declared_apis=["chat_completions"],
        )
        for k in ("a", "b")
    ]
    model = await create_model(
        admin,
        context_window=1000,
        max_output=100,
        budget_price=PRICE,
        capabilities={
            k: "supported"
            for k in ("streaming", "tools", "vision", "reasoning", "structured_output")
        },
        reasoning_options=[{"type": "effort", "values": ["low", "high"]}],
        routing={
            "mode": "auto" if auto else "fixed",
            "fallback": True,
            "model_revision": "chat-v1",
        },
        access={
            "enabled": not auto,
            "audience": "organization",
            **({} if auto else {"channel_id": channels[0]["id"], "upstream_id": "vendor-chat"}),
        },
        bindings=[
            {
                "channel_id": ch["id"],
                "upstream_id": "vendor-chat",
                "enabled": True,
                "priority": 10 - i,
                "compatibility_key": "chat-v1",
                "price": PRICE,
            }
            for i, ch in enumerate(channels)
        ],
    )
    if auto:
        for ch in channels:
            result = await admin.api.post(
                BASE + model["id"] + "/test/chat",
                params={"channel_id": ch["id"], "upstream_id": "vendor-chat"},
                json=payload(model),
            )
            assert result.status_code == 200, result.text
    if auto:
        model = await update(admin, model, access={"enabled": True, "audience": "organization"})
    return model, channels


def payload(model, **kwargs):
    return {
        "model": model["slug"],
        "messages": [{"role": "user", "content": "private prompt"}],
        **kwargs,
    }


async def credentials(env, monkeypatch, api, member, model):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock(return_value=True))
    root, _ = await login(env, monkeypatch, api, member)
    response = await api.post(
        "/api/v1/desktop/resource-tokens",
        headers=bearer(root),
        json={"resource": "llm:" + model["id"]},
    )
    assert response.status_code == 200, response.text
    return root, response.json()


async def entries(admin):
    response = await admin.api.get("/api/v1/llm/settlements")
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def test_chat_stream_tools_reasoning_fallback_and_no_splicing(env):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, auto=True)
        state["calls"].clear()
        state["statuses"] = {"a": 503}
        state["tools"] = True
        result = await admin.api.post(
            BASE + model["id"] + "/test/chat",
            json=payload(
                model,
                stream=True,
                reasoning_effort="high",
                tools=[{"type": "function", "function": {"name": "lookup"}}],
            ),
        )
        assert result.status_code == 200, result.text
        assert [c[0] for c in state["calls"]] == ["a", "b"]
        assert (
            "[DONE]" in result.text
            and "reasoning_content" in result.text
            and "call_1" in result.text
        )
        assert "upstream private detail" not in result.text
        sent = state["calls"][-1][1]
        assert sent["model"] == "vendor-chat" and sent["max_completion_tokens"] == 100
        assert (
            sent["reasoning_effort"] == "high" and sent["stream_options"]["include_usage"] is True
        )
        state["broken"] = True
        state["statuses"] = {}
        state["calls"].clear()
        result = await admin.api.post(
            BASE + model["id"] + "/test/chat", json=payload(model, stream=True)
        )
        assert (
            result.status_code == 200 and '"error"' not in result.text and "[DONE]" in result.text
        )
        assert len(state["calls"]) == 1
        log = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert not log["attempts"][0]["upstream_terminal"]
        assert "private prompt" not in str(log) and "reason" not in str(log["usage"])
        assert not await entries(admin)  # Admin diagnostics never spend member quota.


async def test_native_exact_settlement_snapshots_idempotency_and_visibility(env, monkeypatch):
    admin = await env.client()
    member = await env.client(role="member")
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            root, token = await credentials(env, monkeypatch, api, member, model)
            headers = {**bearer(token), "idempotency-key": "call-1"}
            response = await api.post(GATEWAY, headers=headers, json=payload(model))
            assert response.status_code == 200, response.text
            row = (await entries(admin))[0]
            assert (
                row["status"] == "settled"
                and row["points"] == "0.0244"
                and row["reserved_points"] == "0"
            )
            duplicate = await api.post(GATEWAY, headers=headers, json=payload(model))
            assert duplicate.status_code == 409 and len(state["calls"]) == 1
            mine = await api.get("/api/v1/desktop/llm/usage", headers=bearer(root))
            assert mine.status_code == 200 and len(mine.json()["items"]) == 1
            assert not any(
                word in mine.text for word in ("currency", "price", "ratio", "private prompt")
            )
            quota = (await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))).json()
            assert quota["windows"][0]["remaining"] == "99.9756"
            assert quota["windows"][0]["resets_at"] and quota["windows"][0]["started_at"]
            assert (await member.api.get("/api/v1/llm/settlements")).status_code == 403
            assert (await admin.api.get("/api/v1/desktop/llm/quota")).status_code == 401
            changed = await update(admin, model, budget_price=PRICE | {"input": "99"})
            assert changed["version"] > model["version"]
            conversion = await admin.api.put(
                "/api/v1/llm/point-conversion",
                json={"version": 1, "currency": "USD", "points_per_currency": "200"},
            )
            assert conversion.status_code == 200, conversion.text
            assert (await entries(admin))[0]["points"] == "0.0244"
            currency = await admin.api.put(
                "/api/v1/llm/point-conversion",
                json={"version": 2, "currency": "CNY", "points_per_currency": "200"},
            )
            assert currency.status_code == 409


async def test_concurrent_admission_unknown_usage_reconcile_and_no_double_settlement(
    env, monkeypatch
):
    admin = await env.client()
    await billing(admin, points="0.3")
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            root, token = await credentials(env, monkeypatch, api, admin, model)
            state["usage"] = None
            state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
            pending = asyncio.create_task(
                api.post(GATEWAY, headers=bearer(token), json=payload(model))
            )
            await asyncio.wait_for(state["entered"].wait(), 5)
            rejected = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            assert rejected.status_code == 429, rejected.text
            assert len(state["calls"]) == 1
            held = (await entries(admin))[0]
            assert held["status"] == "reserved" and held["reserved_points"] == "0.28"
            path = "/api/v1/llm/settlements/" + held["id"] + "/reconcile"
            assert (
                await admin.api.post(
                    path,
                    json={"version": held["version"], "action": "release", "reason": "too early"},
                )
            ).status_code == 409
            state["release"].set()
            assert (await pending).status_code == 200
            row = (await entries(admin))[0]
            assert row["status"] == "review" and row["points"] is None
            assert (
                await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            ).status_code == 429
            body = {
                "version": row["version"],
                "action": "settle",
                "usage": {"input": 80, "output": 10, "cache_read": 20},
                "reason": "Verified upstream statement",
            }
            assert (
                await admin.api.post(path, json=body, headers={"x-csrf-token": "bad"})
            ).status_code == 403
            result = await admin.api.post(path, json=body)
            assert result.status_code == 200, result.text
            assert result.json()["items"][0]["points"] == "0.0244"
            assert (await admin.api.post(path, json=body)).status_code == 409
            # Smaller output reserve fits after actual settlement releases the excess.
            state["usage"] = METER
            result = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, max_tokens=50)
            )
            assert result.status_code == 200, result.text
            quota = (await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))).json()
            assert quota["windows"][0]["used"] == "0.0488"


async def test_policy_change_keeps_consumption_and_pending_crosses_reset(env, monkeypatch):
    admin = await env.client()
    policy = await billing(admin, rules=[hours("100"), week("800")])
    app, state = upstream()
    stamp = datetime(2026, 9, 25, 1, tzinfo=UTC)
    monkeypatch.setattr(settlement, "now", lambda: stamp)
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            root, token = await credentials(env, monkeypatch, api, admin, model)
            response = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            assert response.status_code == 200, response.text
            # Align persisted creation with the deterministic accounting clock.
            async with env.sessions() as db:
                row = await db.scalar(select(UsageSettlement))
                row.created_at = stamp
                await db.commit()
            assert (await edit(admin, policy, rules=[hours("200"), week("900")])).status_code == 200
            quota = (await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))).json()
            assert (
                quota["windows"][0]["used"] == "0.0244"
                and quota["windows"][0]["remaining"] == "199.9756"
            )
            assert quota["windows"][1]["resets_at"] == "2026-09-27T16:00:00Z"
            state["usage"] = None
            assert (
                await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            ).status_code == 200
            stamp += timedelta(hours=6)
            quota = (await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))).json()
            assert quota["windows"][0]["used"] == "0" and quota["windows"][0]["reserved"] == "0.28"
            assert quota["windows"][0]["started_at"] is None
            review = next(e for e in await entries(admin) if e["status"] == "review")
            result = await admin.api.post(
                "/api/v1/llm/settlements/" + review["id"] + "/reconcile",
                json={
                    "version": review["version"],
                    "action": "release",
                    "reason": "Confirmed unused",
                },
            )
            assert result.status_code == 200, result.text
            quota = (await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))).json()
            assert quota["windows"][0]["remaining"] == "200"
            async with env.sessions() as db:
                clock = await db.get(QuotaClock, admin.member.id)
                assert datetime.fromisoformat(clock.windows["5"]["start"]) < stamp
                amounts = list(await db.scalars(select(UsageSettlement.amount)))
                assert Decimal("0.000244") in amounts


async def test_missing_billing_invalid_capabilities_and_cancelled_hold(env, monkeypatch):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            assert (
                await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            ).status_code == 409
            assert not state["calls"]
            await billing(admin)
            for extension in (
                {"max_tokens": 101},
                {"unknown": True},
            ):
                result = await api.post(
                    GATEWAY, headers=bearer(token), json=payload(model, **extension)
                )
                assert result.status_code == 422, result.text
            assert not await entries(admin)
            state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
            pending = asyncio.create_task(
                api.post(GATEWAY, headers=bearer(token), json=payload(model, stream=True))
            )
            await asyncio.wait_for(state["entered"].wait(), 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            state["release"].set()
            row = (await entries(admin))[0]
            assert row["status"] == "review" and row["reserved_points"] == "0.28"


async def test_stream_deadline_after_first_event_keeps_hold_and_stops_fallback(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, auto=True)
        model = await update(admin, model, routing={**model["routing"], "total_timeout_seconds": 3})
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            state["calls"] = []
            state["after_first"], state["continue_stream"] = asyncio.Event(), asyncio.Event()
            try:
                result = await asyncio.wait_for(
                    api.post(GATEWAY, headers=bearer(token), json=payload(model, stream=True)), 5
                )
                assert result.status_code == 200 and '"error"' in result.text
                assert "[DONE]" not in result.text and len(state["calls"]) == 1
                assert (await entries(admin))[0]["status"] == "review"
            finally:
                state["continue_stream"].set()


async def test_uncertain_attempt_then_success_still_requires_total_usage_review(env, monkeypatch):

    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, auto=True)
        model = await update(admin, model, routing={**model["routing"], "retry_uncertain": True})
        import httpx
        import httpx2

        from app.modules.llm.providers.sdk_transport import RuntimeTransport

        original = RuntimeTransport.handle_async_request

        async def uncertain(transport, request):
            if "/a/" in str(request.url):
                transport.sent = True
                transport.trace.mark_sent()
                transport.failed(httpx2.ReadTimeout("synthetic timeout"))
                raise httpx.ReadTimeout("synthetic timeout")
            return await original(transport, request)

        monkeypatch.setattr(RuntimeTransport, "handle_async_request", uncertain)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            response = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            assert response.status_code == 200, response.text
            row = (await entries(admin))[0]
            assert row["status"] == "review" and row["reserved_points"] == "0.84"
            assert row["usage"]["output_tokens"] == 10


async def test_cancel_after_stream_started_closes_upstream_and_preserves_hold(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        model = await update(admin, model, reasoning_options=[{"type": "toggle"}])
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            invalid = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, max_tokens=101)
            )
            assert invalid.status_code == 422 and not await entries(admin)
            state["after_first"], state["continue_stream"] = asyncio.Event(), asyncio.Event()
            pending = asyncio.create_task(
                api.post(GATEWAY, headers=bearer(token), json=payload(model, stream=True))
            )
            await asyncio.wait_for(state["after_first"].wait(), 5)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            state["continue_stream"].set()
            async with asyncio.timeout(5):
                while (row := (await entries(admin))[0])["status"] == "reserved":
                    await asyncio.sleep(0.02)
            assert row["status"] == "review" and row["reserved_points"] == "0.28"
            assert len(state["calls"]) == 1
