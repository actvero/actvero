"""Idempotency receipts stay member-scoped and manual conflicts have no side effects."""

from unittest.mock import AsyncMock

import pytest
from llm_billing_helpers import billing
from sqlalchemy import func, select
from test_access_keys import create as create_key
from test_access_keys import headers as key_headers
from test_desktop import bearer, login, native_client
from test_identity_access import env as identity_env
from test_llm_execution import GATEWAY, configured, payload, upstream
from test_llm_routing import update
from test_mcp import listening

from app.modules.audit.models import AuditEvent
from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm import settlement_router
from app.modules.llm.models import ModelCall, UsageSettlement

pytestmark = pytest.mark.asyncio
env = identity_env


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock(return_value=True))


async def desktop_credential(env, monkeypatch, api, member, model, device_name):
    root, _ = await login(env, monkeypatch, api, member, device_name=device_name)
    response = await api.post(
        "/api/v1/desktop/resource-tokens",
        headers=bearer(root),
        json={"resource": "llm:" + model["id"]},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_cross_credential_receipt_requires_current_permission_and_member_scope(
    env, monkeypatch
):
    admin = await env.client()
    member = await env.client(role="member")
    other = await env.client(role="member")
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        first_key, _ = await create_key(member)
        second_key, _ = await create_key(member)
        other_key, _ = await create_key(other)
        request_body = payload(model)
        idempotency = "member-cross-credential-call"
        async with native_client(env) as api:
            first = await api.post(
                GATEWAY,
                headers={**key_headers(first_key), "idempotency-key": idempotency},
                json=request_body,
            )
            assert first.status_code == 200, first.text
            async with env.sessions() as db:
                owner = await db.scalar(
                    select(UsageSettlement).where(UsageSettlement.member_id == member.member.id)
                )
                assert owner is not None and owner.request_fingerprint is not None
                owner_id, fingerprint = str(owner.id), owner.request_fingerprint

            desktop_a = await desktop_credential(env, monkeypatch, api, member, model, "desktop-A")
            desktop_b = await desktop_credential(env, monkeypatch, api, member, model, "desktop-B")
            for credential in (second_key, desktop_a, desktop_b):
                auth = key_headers(credential) if credential is second_key else bearer(credential)
                retry = await api.post(
                    GATEWAY,
                    headers={**auth, "idempotency-key": idempotency},
                    json=request_body,
                )
                assert retry.status_code == 409, retry.text
                receipt = retry.json()["error"]
                assert receipt["code"] == "duplicate_request"
                assert receipt["call_id"] == owner_id
                assert receipt["call_status"] == "succeeded"
                assert receipt["settlement_status"] == "settled"
                assert "private prompt" not in retry.text and fingerprint not in retry.text
            assert len(state["calls"]) == 1

            # Different members may reuse a client-generated key. Neither their
            # first call nor their later receipt reveals the first member's call.
            other_first = await api.post(
                GATEWAY,
                headers={**key_headers(other_key), "idempotency-key": idempotency},
                json=request_body,
            )
            assert other_first.status_code == 200, other_first.text
            other_retry = await api.post(
                GATEWAY,
                headers={**key_headers(other_key), "idempotency-key": idempotency},
                json=request_body,
            )
            assert other_retry.status_code == 409
            assert other_retry.json()["error"]["call_id"] != owner_id
            assert owner_id not in other_first.text + other_retry.text
            assert len(state["calls"]) == 2

            model = await update(
                admin,
                model,
                access={**model["access"], "enabled": False},
            )
            denied = await api.post(
                GATEWAY,
                headers={**bearer(desktop_a), "idempotency-key": idempotency},
                json=request_body,
            )
            assert denied.status_code in (403, 404)
            assert "call_id" not in denied.text and owner_id not in denied.text
            assert len(state["calls"]) == 2

            model = await update(
                admin,
                model,
                access={**model["access"], "enabled": True},
            )
            revoked = await member.api.patch(
                "/api/v1/account/access-keys/" + first_key["key"]["id"],
                json={"version": first_key["key"]["version"], "action": "revoke"},
            )
            assert revoked.status_code == 200, revoked.text
            denied_key = await api.post(
                GATEWAY,
                headers={**key_headers(first_key), "idempotency-key": idempotency},
                json=request_body,
            )
            assert denied_key.status_code in (401, 403)
            assert "call_id" not in denied_key.text and owner_id not in denied_key.text
            assert len(state["calls"]) == 2


async def test_manual_post_lock_false_cannot_write_reason_or_audit(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    state["usage"] = {"prompt_tokens": 10, "completion_tokens": 2}
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        # The cache bucket is priced by this fixture and absent upstream.
        async with native_client(env) as api:
            desktop = await desktop_credential(env, monkeypatch, api, admin, model, "review")
            response = await api.post(GATEWAY, headers=bearer(desktop), json=payload(model))
            assert response.status_code == 200, response.text
        async with env.sessions() as db:
            row = await db.scalar(select(UsageSettlement))
            assert row is not None and row.status == "review"
            call = await db.get(ModelCall, row.id)
            assert call is not None and call.status == "succeeded"
            call_id, version, reason = row.id, row.version, row.reason
            before = await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "llm.settlement.reconcile")
            )

        # Model the result of a competing completion after the route's initial
        # read. This tests the false-return branch, not two live administrators.
        monkeypatch.setattr(settlement_router.settlement, "complete", AsyncMock(return_value=False))
        result = await admin.api.post(
            f"/api/v1/llm/settlements/{call_id}/reconcile",
            json={"version": version, "action": "release", "reason": "stale manual decision"},
        )
        assert result.status_code == 409, result.text
        assert result.json()["error"]["code"] == "settlement_changed"
        async with env.sessions() as db:
            fresh = await db.get(UsageSettlement, call_id)
            after = await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "llm.settlement.reconcile")
            )
            assert fresh is not None
            assert (fresh.status, fresh.version, fresh.reason) == ("review", version, reason)
            assert before == after
