"""G6 admission invariants against an isolated PostgreSQL schema and loopback SDK upstream."""

import asyncio
import json
from datetime import timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from llm_billing_helpers import billing
from sqlalchemy import select
from test_access_keys import create as create_key
from test_access_keys import headers as key_headers
from test_desktop import bearer, native_client
from test_identity_access import env as identity_env
from test_llm_execution import GATEWAY, configured, credentials, payload, upstream
from test_llm_routing import update
from test_mcp import listening

from app.modules.auth.service import now
from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.models import ModelCall, UsageSettlement
from app.modules.llm.providers.sdk_transport import RuntimeTransport

env = identity_env
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock(return_value=True))


async def stored(env):
    async with env.sessions() as db:
        calls = list(
            await db.scalars(
                select(ModelCall).join(UsageSettlement, UsageSettlement.id == ModelCall.id)
            )
        )
        settlements = list(await db.scalars(select(UsageSettlement)))
        return calls, settlements


async def test_same_key_is_one_call_and_changed_body_is_a_safe_conflict(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            root, token = await credentials(env, monkeypatch, api, member, model)
            headers = {**bearer(token), "idempotency-key": "same-logical-call"}
            state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
            first = asyncio.create_task(api.post(GATEWAY, headers=headers, json=payload(model)))
            await asyncio.wait_for(state["entered"].wait(), 5)
            duplicate = await api.post(GATEWAY, headers=headers, json=payload(model))
            assert duplicate.status_code == 409, duplicate.text
            assert duplicate.json()["error"]["code"] == "duplicate_request"
            assert len(state["calls"]) == 1
            state["release"].set()
            assert (await first).status_code == 200
            calls, settlements = await stored(env)
            assert len(calls) == len(settlements) == 1
            row = settlements[0]
            receipt = duplicate.json()["error"]
            assert receipt["call_id"] == str(calls[0].id)
            assert receipt["call_status"] in {"pending", "succeeded"}
            assert receipt["settlement_status"] in {"reserved", "settled"}
            assert row.request_fingerprint is not None
            assert len(row.request_fingerprint) == 67
            assert "private prompt" not in row.request_fingerprint
            assert "same-logical-call" not in row.request_fingerprint
            changed = await api.post(
                GATEWAY,
                headers=headers,
                json=payload(
                    model, messages=[{"role": "user", "content": "different private body"}]
                ),
            )
            assert changed.status_code == 409, changed.text
            assert changed.json()["error"]["code"] == "idempotency_conflict"
            assert changed.json()["error"]["call_id"] == str(calls[0].id)
            assert len(state["calls"]) == 1
            assert "private prompt" not in changed.text
            assert "different private body" not in changed.text
            assert row.request_fingerprint not in changed.text
            # Pre-G6 rows cannot prove body equality, so their old key stays safely spent.
            async with env.sessions() as db:
                legacy = await db.get(UsageSettlement, row.id)
                legacy.request_fingerprint = None
                await db.commit()
            legacy_retry = await api.post(GATEWAY, headers=headers, json=payload(model))
            assert legacy_retry.status_code == 409
            assert legacy_retry.json()["error"]["code"] == "duplicate_request"
            assert len(state["calls"]) == 1
            mine = await api.get("/api/v1/desktop/llm/usage", headers=bearer(root))
            assert mine.status_code == 200
            assert mine.json()["items"][0]["id"] == str(calls[0].id)


async def test_one_member_key_and_desktop_share_the_same_reserved_quota(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin, points="0.3")
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        key, _ = await create_key(member)
        async with native_client(env) as api:
            root, token = await credentials(env, monkeypatch, api, member, model)
            state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
            first = asyncio.create_task(
                api.post(
                    GATEWAY,
                    headers={**key_headers(key), "idempotency-key": "key-credential-call"},
                    json=payload(model),
                )
            )
            await asyncio.wait_for(state["entered"].wait(), 5)
            denied = await api.post(
                GATEWAY,
                headers={**bearer(token), "idempotency-key": "desktop-credential-call"},
                json=payload(model),
            )
            assert denied.status_code == 429, denied.text
            assert denied.json()["error"]["code"] == "quota_exceeded"
            assert len(state["calls"]) == 1
            calls, settlements = await stored(env)
            assert len(calls) == len(settlements) == 1
            assert calls[0].source == "access_key"
            assert settlements[0].member_id == member.member.id
            assert settlements[0].status == "reserved"
            quota = await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))
            assert quota.status_code == 200
            assert quota.json()["windows"][0]["reserved"] == "0.28"
            state["release"].set()
            assert (await first).status_code == 200
            final = (await stored(env))[1][0]
            assert final.status == "settled", final.evidence


async def test_unknown_first_attempt_then_success_retains_review_and_attempts(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base, auto=True)
        model = await update(admin, model, routing={**model["routing"], "retry_uncertain": True})
        state["calls"].clear()
        original = RuntimeTransport.handle_async_request

        async def lost_after_upstream(self, request):
            response = await original(self, request)
            if "/a/" in str(request.url):
                await response.aread()
                await response.aclose()
                raise httpx.ReadTimeout("synthetic lost response", request=request)
            return response

        monkeypatch.setattr(RuntimeTransport, "handle_async_request", lost_after_upstream)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            assert result.status_code == 200, result.text
            assert [item[0] for item in state["calls"]] == ["a", "b"]
            calls, settlements = await stored(env)
            assert len(calls) == len(settlements) == 1
            call, row = calls[0], settlements[0]
            assert call.status == "succeeded" and len(call.attempts) == 2
            first, second = call.attempts
            assert first["status"] == "failed" and first["uncertain"] is True
            assert first["sent"] is True and first["attempt_id"] != second["attempt_id"]
            assert second["status"] == "succeeded" and second["sent"] is True
            assert row.status == "review" and row.amount is None
            assert row.reserved_amount > 0
            assert call.usage["output_tokens"] == 10
            assert row.evidence["evidence_version"] == 1
            assert len(row.evidence["attempts"]) == 2
            assert row.evidence["attempts"][0]["uncertain"] is True
            assert row.evidence["attempts"][1]["status"] == "succeeded"
            assert "private prompt" not in json.dumps([call.attempts, row.usage, row.evidence])


async def test_late_completion_cannot_override_manual_versioned_release(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
            pending = asyncio.create_task(
                api.post(GATEWAY, headers=bearer(token), json=payload(model))
            )
            await asyncio.wait_for(state["entered"].wait(), 5)
            calls, settlements = await stored(env)
            assert len(calls) == len(settlements) == 1
            row = settlements[0]
            assert row.status == "reserved" and row.version == 1
            # Simulate a long-running request after the existing ten-minute review guard.
            async with env.sessions() as db:
                stored_row = await db.get(UsageSettlement, row.id)
                stored_row.created_at = now() - timedelta(minutes=11)
                await db.commit()
            path = f"/api/v1/llm/settlements/{row.id}/reconcile"
            reviewed = await admin.api.post(
                path,
                json={
                    "version": row.version,
                    "action": "release",
                    "reason": "Independent statement confirms no billable charge",
                },
            )
            assert reviewed.status_code == 200, reviewed.text
            assert reviewed.json()["items"][0]["status"] == "released"
            state["release"].set()
            assert (await pending).status_code == 200
            calls, settlements = await stored(env)
            assert len(state["calls"]) == len(calls) == len(settlements) == 1
            final = settlements[0]
            assert final.status == "released" and final.amount == 0
            assert final.version == row.version + 1
            assert final.reason == "Independent statement confirms no billable charge"
            stale = await admin.api.post(
                path,
                json={"version": row.version, "action": "release", "reason": "Duplicate decision"},
            )
            assert stale.status_code == 409
