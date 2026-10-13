"""G7 cross-layer acceptance over the member catalog and historical usage."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from llm_billing_helpers import billing
from sqlalchemy import select
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_routing import update
from test_mcp import listening
from test_settlement_metrics_runtime import configured, upstream

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.models import ModelCall, UsageSettlement

env = identity_env
pytestmark = pytest.mark.asyncio


async def test_member_catalog_revoke_and_historical_result_settlement_axes(env, monkeypatch):
    """A revoked model vanishes now, while an actual SDK call remains honestly billable."""
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock(return_value=True))
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    other = await env.client(role="member", tenant=admin.tenant)
    await billing(admin)
    app, state = upstream()
    state["chat_usage"] = {}  # SDK success with no raw priced cache must remain review.
    async with listening(app) as base:
        model = await configured(
            env,
            admin,
            base,
            "chat",
            {"currency": "USD", "input": "1", "output": "1", "cache_read": "0.2"},
        )
        key, _ = await create_key(member)

        account = await member.api.get("/api/v1/account/llm/models", params={"operation": "chat"})
        assert account.status_code == 200, account.text
        items = account.json()["items"]
        assert len(items) == account.json()["total"] == 1
        assert items[0]["id"] == model["id"] and items[0]["slug"] == model["slug"]
        assert items[0]["operations"][0]["endpoint"]["path"] == "/api/llm/v1/chat/completions"
        assert "secret" not in account.text and "sealed_key" not in account.text

        async with native_client(env) as api:
            public = await api.get("/api/llm/v1/models", headers=headers(key))
            assert public.status_code == 200, public.text
            assert [item["id"] for item in public.json()["data"]] == [model["slug"]]
            assert (
                await api.get("/api/v1/account/llm/models", headers=headers(key))
            ).status_code == 401
            result = await api.post(
                "/api/llm/v1/chat/completions",
                headers=headers(key),
                json={
                    "model": model["slug"],
                    "messages": [{"role": "user", "content": "private request body"}],
                },
            )
            assert result.status_code == 200, result.text
            assert len(state["calls"]) == 1

        async with env.sessions() as db:
            first = await db.scalar(
                select(UsageSettlement).where(UsageSettlement.member_id == member.member.id)
            )
            assert first is not None and first.status == "review"
            old_call = await db.get(ModelCall, first.id)
            assert old_call is not None and old_call.status == "succeeded"
            second_id = uuid4()
            db.add(
                ModelCall(
                    id=second_id,
                    tenant_id=admin.tenant.id,
                    model_id=UUID(model["id"]),
                    channel_id=old_call.channel_id,
                    actor_id=member.user.id,
                    source="desktop",
                    kind="chat",
                    status="failed",
                    termination_code="upstream_timeout",
                    attempts=[],
                    usage={},
                )
            )
            db.add(
                UsageSettlement(
                    id=second_id,
                    tenant_id=admin.tenant.id,
                    member_id=member.member.id,
                    conversion_id=first.conversion_id,
                    currency=first.currency,
                    ratio=first.ratio,
                    reserved_amount=Decimal("0.001"),
                    amount=Decimal("0.001"),
                    price=first.price,
                    policy_snapshot=first.policy_snapshot,
                    usage={},
                    status="settled",
                    version=1,
                    reason="private administrator note",
                    created_at=datetime.now(UTC),
                    settled_at=datetime.now(UTC),
                )
            )
            await db.commit()

        history = await member.api.get("/api/v1/account/llm/usage")
        assert history.status_code == 200, history.text
        by_id = {item["id"]: item for item in history.json()["items"]}
        assert history.json()["total"] == 2
        assert (
            by_id[str(first.id)]["result_status"],
            by_id[str(first.id)]["settlement_status"],
        ) == ("success", "review")
        assert (
            by_id[str(second_id)]["result_status"],
            by_id[str(second_id)]["settlement_status"],
        ) == ("failed", "settled")
        assert by_id[str(second_id)]["status"] == "settled"  # Legacy reader contract.
        assert by_id[str(second_id)]["terminal_reason"] == "upstream_timeout"
        assert "private administrator note" not in history.text
        assert "private request body" not in history.text
        for field in ("price", "amount", "ratio", "currency", "channel_id", "upstream_id"):
            assert field not in history.text
        assert (await other.api.get("/api/v1/account/llm/usage")).json()["total"] == 0

        # Revocation changes future availability, never the already recorded outcome or debt.
        model = await update(admin, model, access={"enabled": False, "audience": "organization"})
        assert (await member.api.get("/api/v1/account/llm/models")).json()["total"] == 0
        async with native_client(env) as api:
            public = await api.get("/api/llm/v1/models", headers=headers(key))
            assert public.status_code == 200 and public.json()["data"] == []
        after = await member.api.get("/api/v1/account/llm/usage")
        assert after.status_code == 200 and after.json()["total"] == 2
        assert {item["id"]: item["settlement_status"] for item in after.json()["items"]} == {
            str(first.id): "review",
            str(second_id): "settled",
        }
