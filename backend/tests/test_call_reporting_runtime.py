"""Reporting over actual locked SDK execution, not manufactured call JSON."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from llm_billing_helpers import billing
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_mcp import listening
from test_settlement_metrics_runtime import configured, upstream

from app.modules.desktop.oidc import NativeIdentity

env = identity_env
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


@pytest.mark.parametrize("missing", [False, True])
async def test_real_sdk_call_is_reported_without_promoting_missing_meter_or_diagnostics(
    env, missing
):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    await billing(admin)
    app, state = upstream()
    state["chat_usage"] = (
        {}
        if missing
        else {
            "prompt_tokens": 10,
            "completion_tokens": 2,
            "prompt_tokens_details": {"cached_tokens": 3},
        }
    )
    async with listening(app) as base:
        model = await configured(
            env,
            admin,
            base,
            "chat",
            {"currency": "USD", "input": "1", "output": "1", "cache_read": "0.2"},
        )
        key, _ = await create_key(member)
        body = {
            "model": model["slug"],
            "messages": [{"role": "user", "content": "PRIVATE-PROMPT-NOT-IN-REPORTS"}],
        }
        async with native_client(env) as api:
            response = await api.post(
                "/api/llm/v1/chat/completions", headers=headers(key), json=body
            )
        assert response.status_code == 200, response.text
        diagnostic = await admin.api.post(f"/api/v1/llm/models/{model['id']}/test/chat", json=body)
        assert diagnostic.status_code == 200, diagnostic.text
        assert len(state["calls"]) == 2

    calls = (await admin.api.get("/api/v1/llm/calls")).json()
    assert calls["total"] == 1
    call = calls["items"][0]
    assert call["member_id"] == str(member.member.id)
    assert call["result_status"] == "success"
    assert call["settlement_status"] == ("review" if missing else "settled")
    detail = await admin.api.get(f"/api/v1/llm/calls/{call['id']}")
    assert detail.status_code == 200, detail.text
    assert "PRIVATE-PROMPT" not in detail.text and "local answer" not in detail.text
    assert detail.json()["attempts"][0]["sent"] is True
    assert detail.json()["attempts"][0]["client_terminal"] is None

    now = datetime.now(UTC)
    params = {
        "from": (now - timedelta(minutes=1)).isoformat(),
        "to": (now + timedelta(minutes=1)).isoformat(),
        "timezone": "UTC",
    }
    summary = await admin.api.get("/api/v1/llm/usage-summary", params=params)
    assert summary.status_code == 200, summary.text
    data = summary.json()
    assert data["calls"] == data["attempts"] == 1
    metrics = {bucket["field"]: bucket for bucket in data["metrics"]}
    for field, value in (("input_tokens", 7), ("output_tokens", 2), ("cache_read_tokens", 3)):
        assert metrics[field]["known_calls"] == (0 if missing else 1)
        assert metrics[field]["unknown_calls"] == (1 if missing else 0)
        assert metrics[field]["sum"] == str(0 if missing else value)
    if missing:
        assert Decimal(data["current_held"]["points"]) > 0
        assert Decimal(data["settled_points"]) == 0
    else:
        assert Decimal(data["current_held"]["points"]) == 0
        assert Decimal(data["settled_points"]) == Decimal("0.00096")

    diagnostic_summary = await admin.api.get(
        "/api/v1/llm/usage-summary", params=params | {"source": "diagnostic"}
    )
    assert diagnostic_summary.status_code == 200, diagnostic_summary.text
    diagnostics = diagnostic_summary.json()
    assert diagnostics["calls"] == 1 and diagnostics["settled_points"] is None
    assert diagnostics["current_held"]["applicable"] is False
