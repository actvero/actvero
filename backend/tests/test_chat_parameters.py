"""Parameter policy through isolated PostgreSQL and real SDK / loopback HTTP."""

import asyncio
from copy import deepcopy

import pytest
from llm_billing_helpers import billing
from test_desktop import bearer, native_client
from test_identity_access import env as identity_env
from test_llm_execution import BASE, GATEWAY, configured, credentials, entries, payload, upstream
from test_llm_routing import update
from test_mcp import listening

from app.modules.llm.catalog_schemas import CatalogInput

pytestmark = pytest.mark.asyncio
env = identity_env
POLICY = {
    "default_context_window": 800,
    "default_max_output": 50,
    "default_reasoning_effort": "low",
    "temperature": {"default": 0.4, "min": 0.2, "max": 0.8, "adjustable": False},
    "top_p": {"default": 0.9, "min": 0.5, "max": 1},
}


async def test_defaults_catalog_version_and_private_metadata(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        model = await update(admin, model, chat_policy=POLICY, description="正式模型说明")
        async with native_client(env) as api:
            root, token = await credentials(env, monkeypatch, api, admin, model)
            directory = await api.post(
                "/api/v1/desktop/resource-tokens",
                headers=bearer(root),
                json={"resource": "llm:catalog"},
            )
            listing = await api.get("/api/llm/v1/models", headers=bearer(directory.json()))
            assert listing.status_code == 200, listing.text
            public = listing.json()["data"][0]
            assert (
                public["configuration_version"] == model["version"]
                and public["description"] == "正式模型说明"
            )
            operation = public["operations"][0]
            assert operation["chat_policy"]["temperature"]["default"] == 0.4
            assert operation["pricing_status"] == "ready" and operation["parameter_routes"]
            assert not any(
                k in listing.text
                for k in ["base_url", "sealed_key", "procurement", "test-secret", "channel_id"]
            )
            result = await api.post(
                GATEWAY,
                headers=bearer(token),
                json=payload(
                    model,
                    actvero={"configuration_version": model["version"], "purpose": "compaction"},
                ),
            )
            assert result.status_code == 200, result.text
            sent = state["calls"][0][1]
            assert sent["temperature"] == 0.4 and sent["top_p"] == 0.9
            assert sent["max_completion_tokens"] == 50 and sent["reasoning_effort"] == "low"
            assert "actvero" not in sent and "context_window" not in sent
            assert (await entries(admin))[0]["status"] == "settled"
            stale = await api.post(
                GATEWAY,
                headers=bearer(token),
                json=payload(model, actvero={"configuration_version": model["version"] - 1}),
            )
            assert stale.status_code == 200, stale.text
            assert len(state["calls"]) == 2


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"temperature": 0.7}, "parameter_not_allowed"),
        ({"top_p": 0.2}, "parameter_not_allowed"),
        ({"max_completion_tokens": 101}, "output_limit_required"),
        ({"actvero": {"context_window": 1001}}, "context_limit_exceeded"),
        ({"actvero": {"context_window": 40}}, "context_limit_exceeded"),
    ],
)
async def test_invalid_parameters_never_call_or_reserve(env, monkeypatch, changes, code):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        model = await update(admin, model, chat_policy=POLICY)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            response = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, **changes)
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == code
            assert not state["calls"] and not await entries(admin)


async def test_parameter_filter_before_priority(env, monkeypatch):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    async with listening(app) as base:
        model, channels = await configured(env, admin, base)
        bindings = deepcopy(model["bindings"])
        bindings[0]["priority"] = 10
        bindings[1]["priority"] = 9
        bindings[0]["chat_options"]["limits"] = {
            "reasoning_efforts": ["low"],
            "context_window": 600,
        }
        bindings[1]["chat_options"]["limits"] = {
            "reasoning_efforts": ["high", "low"],
            "context_window": 1000,
        }
        model = await update(
            admin,
            model,
            bindings=bindings,
            routing={**model["routing"], "mode": "auto", "model_revision": "chat-v1"},
            access={**model["access"], "enabled": False},
            chat_policy=POLICY,
        )
        for channel in channels:
            result = await admin.api.post(
                BASE + model["id"] + "/test/chat",
                params={"channel_id": channel["id"], "upstream_id": "vendor-chat"},
                json=payload(model, actvero={"context_window": 500}),
            )
            assert result.status_code == 200, result.text
        model = await update(admin, model, access={**model["access"], "enabled": True})
        state["calls"].clear()
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            high = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, reasoning_effort="high")
            )
            assert high.status_code == 200, high.text
            assert [c[0] for c in state["calls"]] == ["b"]
            low = await api.post(
                GATEWAY,
                headers=bearer(token),
                json=payload(model, reasoning_effort="low", actvero={"context_window": 500}),
            )
            assert low.status_code == 200, low.text
            assert state["calls"][-1][0] == "a" and len(state["calls"]) == 2


async def test_old_client_preserves_policy_and_binding_limits(env):
    admin = await env.client()
    app, _ = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        bindings = deepcopy(model["bindings"])
        bindings[0]["chat_options"]["limits"] = {"max_output": 80, "parameters": ["top_p"]}
        model = await update(admin, model, bindings=bindings, chat_policy=POLICY)
        old = {k: v for k, v in model.items() if k in CatalogInput.model_fields}
        old["version"] = model["version"]
        old.pop("chat_policy")
        old["bindings"][0]["chat_options"].pop("limits")
        old["name"] = "旧客户端更新名字"
        response = await admin.api.put(BASE + model["id"], json=old)
        assert response.status_code == 200, response.text
        assert response.json()["chat_policy"]["default_max_output"] == 50
        assert response.json()["bindings"][0]["chat_options"]["limits"]["max_output"] == 80


async def test_locked_settings_reject_before_admission(env, monkeypatch):
    admin = await env.client()
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        model = await update(
            admin,
            model,
            chat_policy={
                **POLICY,
                "context_adjustable": False,
                "output_adjustable": False,
                "reasoning_adjustable": False,
            },
        )
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            for extra in (
                {"max_tokens": 20},
                {"reasoning_effort": "high"},
                {"actvero": {"context_window": 500}},
            ):
                result = await api.post(
                    GATEWAY, headers=bearer(token), json=payload(model, **extra)
                )
                assert result.status_code == 422, result.text
            assert not state["calls"] and not await entries(admin)


async def test_selected_context_reserves_shared_quota_before_parallel_request(env, monkeypatch):
    admin = await env.client()
    await billing(admin, points="0.26")
    app, state = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        model = await update(admin, model, chat_policy=POLICY)
        async with native_client(env) as api:
            root, token = await credentials(env, monkeypatch, api, admin, model)
            state["entered"], state["release"] = asyncio.Event(), asyncio.Event()
            pending = asyncio.create_task(
                api.post(GATEWAY, headers=bearer(token), json=payload(model))
            )
            try:
                await asyncio.wait_for(state["entered"].wait(), 5)
                held = (await entries(admin))[0]
                assert held["status"] == "reserved" and held["reserved_points"] == "0.24"
                blocked = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
                assert blocked.status_code == 429 and len(state["calls"]) == 1
            finally:
                state["release"].set()
            assert (await pending).status_code == 200
            quota = (await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))).json()
            assert quota["windows"][0]["used"] == "0.0244"
            assert quota["windows"][0]["reserved"] == "0"
