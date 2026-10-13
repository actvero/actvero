"""SDK delivery, optional metering and business routing remain independent."""

import pytest
from fastapi.responses import Response
from llm_billing_helpers import billing
from test_desktop import bearer, native_client
from test_identity_access import env as identity_env
from test_llm_execution import BASE, GATEWAY, configured, credentials, entries, payload, upstream
from test_mcp import listening

from app.modules.llm import chat_policy
from app.modules.llm.catalog_schemas import CatalogInput, ModelBinding
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.models import ModelChannel
from app.modules.llm.providers import sdk
from app.modules.llm.providers.sdk_meter import Meter

env = identity_env


def test_catalog_hints_do_not_veto_sdk_parameters_or_treat_bytes_as_tokens(monkeypatch):
    config = CatalogInput.model_validate(
        {"slug": "public", "name": "Public", "context_window": 1000, "max_output": 100}
    )
    channel = ModelChannel(provider="openai")
    binding = ModelBinding.model_validate(
        {"channel_id": "00000000-0000-0000-0000-000000000001", "upstream_id": "gpt-4o"}
    )

    # Even SDK hints for a known model must not become a second admission policy.
    def unexpected_lookup(*args, **kwargs):
        pytest.fail("model catalog must not validate a live SDK request")

    monkeypatch.setattr(
        sdk.litellm,
        "model_cost",
        {"gpt-4o": {"litellm_provider": "openai", "max_input_tokens": 8, "max_output_tokens": 4}},
    )
    monkeypatch.setattr(sdk.litellm, "get_model_info", unexpected_lookup)
    monkeypatch.setattr(sdk.litellm, "get_supported_openai_params", unexpected_lookup)
    body = ChatInput.model_validate(
        {
            "model": "public",
            "messages": [{"role": "user", "content": "中文和工具历史" * 300}],
            "reasoning_effort": "xhigh",
            "stream": True,
            "tools": [{"type": "function", "function": {"name": "lookup"}}],
            "actvero": {"context_window": 200},
        }
    )
    resolved = chat_policy.resolve(body, config, 1)
    assert chat_policy.supports(resolved, config, binding, channel)
    # An unverified client window cannot lower the budget reservation.
    assert resolved._input_reservation == 1000
    restricted = binding.model_copy(deep=True)
    restricted.chat_options.limits.reasoning_efforts = ["low"]
    assert not chat_policy.supports(resolved, config, restricted, channel)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_meter_failure_delivers_sdk_result_but_keeps_unknown_bill_in_review(
    env, monkeypatch, stream
):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()

    def unsupported_meter(*args, **kwargs):
        raise ValueError("optional observer failed")

    monkeypatch.setattr(Meter, "feed" if stream else "observe", unsupported_meter)
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, stream=stream)
            )
        assert result.status_code == 200 and '"error"' not in result.text, result.text
        assert "[DONE]" in result.text if stream else result.json()["usage"] is None
        rows = await entries(admin)
        assert rows[0]["status"] == "review" and rows[0]["points"] is None
        log = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert log["status"] == "succeeded" and log["usage"] == {"source": "unknown"}
        assert len(state["calls"]) == 1
        health = (await admin.api.get(BASE + model["id"] + "/routes")).json()[0]
        assert health["failures"] == 0 and health["cooldown_until"] is None


@pytest.mark.asyncio
async def test_sdk_parser_failures_do_not_trip_platform_circuit(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    broken = {"enabled": True}

    @app.middleware("http")
    async def corrupt_response(request, call_next):
        response = await call_next(request)
        return (
            Response(content=b"not json", media_type="application/json")
            if broken["enabled"]
            else response
        )

    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            for _ in range(4):
                result = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
                assert result.status_code == 502, result.text
                assert result.json()["error"]["code"] == "sdk_response_error"
            health = (await admin.api.get(BASE + model["id"] + "/routes")).json()[0]
            assert health["failures"] == 0 and health["cooldown_until"] is None
            logs = (await admin.api.get(BASE + model["id"] + "/calls")).json()
            assert all(log["attempts"][0]["error_scope"] == "sdk" for log in logs)
            assert all(row["status"] == "review" for row in await entries(admin))
            broken["enabled"] = False
            result = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            assert result.status_code == 200, result.text
            assert len(state["calls"]) == 5


@pytest.mark.asyncio
async def test_sdk_eof_delivers_without_certification_or_automatic_settlement(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    state["broken"] = True
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, stream=True)
            )
            assert result.status_code == 200 and "[DONE]" in result.text, result.text
            row = (await entries(admin))[0]
            assert row["status"] == "review"
        log = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert not log["attempts"][0]["upstream_terminal"]
        assert log["attempts"][0]["uncertain"]
        health = (await admin.api.get(BASE + model["id"] + "/routes")).json()[0]
        assert health["failures"] == 0 and health["state"] == "ready"
        assert len(state["calls"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_explicit_zero_usage_is_evidence_not_missing_data(env, monkeypatch, stream):
    from decimal import Decimal

    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    state["usage"] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "prompt_tokens_details": {"cached_tokens": 0},
    }
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            result = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, stream=stream)
            )
            assert result.status_code == 200, result.text
        log = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert log["usage"]["source"] == "upstream"
        assert log["usage"]["input_tokens"] == 0 and log["usage"]["output_tokens"] == 0
        row = (await entries(admin))[0]
        assert row["status"] == "settled" and Decimal(row["points"]) == 0
