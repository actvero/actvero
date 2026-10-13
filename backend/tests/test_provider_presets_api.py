"""Ordinary API presets: control-plane boundaries in isolated PostgreSQL.

These tests use fake credentials and never contact a vendor. The SDK transport
and protocol are covered separately by local-upstream tests.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_mcp import listening

from app.modules.audit.models import AuditEvent
from app.modules.llm.models import CatalogModel, ModelChannel
from app.modules.llm.providers import PROVIDERS

env = identity_env
pytestmark = pytest.mark.asyncio

BASE = "/api/v1/llm"
PRESETS = {
    "aihubmix": ("https://aihubmix.com", "/v1", True),
    "volcengine": ("https://ark.cn-beijing.volces.com", "/api/v3", False),
    "zhipu": ("https://open.bigmodel.cn", "/api/paas/v4", False),
    "moonshot": ("https://api.moonshot.cn", "/v1", False),
    "qwen": ("https://maas.qianwenaiapi.com", "/compatible-mode/v1", False),
    "qwen-token-plan": ("https://token-plan.maas.qianwenaiapi.com", "/compatible-mode/v1", False),
}


def fake_key(provider_id):
    return ("sk-sp-fake-" if provider_id == "qwen-token-plan" else "fake-") + provider_id


async def counts(env) -> tuple[int, int, int]:
    async with env.sessions() as db:
        return (
            int(await db.scalar(select(func.count()).select_from(ModelChannel)) or 0),
            int(await db.scalar(select(func.count()).select_from(CatalogModel)) or 0),
            int(await db.scalar(select(func.count()).select_from(AuditEvent)) or 0),
        )


async def test_preset_modules_and_default_preview_are_admin_only_and_no_io(env, monkeypatch):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    listed = await admin.api.get(BASE + "/providers")
    assert listed.status_code == 200, listed.text
    modules = {item["id"]: item for item in listed.json()}
    assert PRESETS.keys() <= modules.keys()
    plan = modules["qwen-token-plan"]
    assert "团队版" in plan["name"]
    assert "qwen3.8-max" in plan["reference_catalog"]["models"]
    assert "deepseek-v4-pro" in plan["reference_catalog"]["models"]
    assert plan["reference_catalog"]["source_url"].endswith("token-plan-team-overview")
    assert modules["qwen"]["reference_catalog"] is None
    assert (await member.api.get(BASE + "/providers")).status_code == 403

    outbound = AsyncMock(side_effect=AssertionError("preview must not inspect upstream models"))
    for adapter in PROVIDERS.values():
        monkeypatch.setattr(adapter, "list_models", outbound)
    before = await counts(env)
    for provider_id, (root, prefix, discovery) in PRESETS.items():
        info = modules[provider_id]
        assert info["official_service_root"] == root
        assert info["default_api_prefix"] == prefix
        assert info["default_base_url"] == root + prefix
        assert info["setup_help"]
        assert info["model_discovery"] is discovery
        assert info["balance_query"] is False
        assert info["allow_no_auth"] is False
        assert info["default_apis"] == ["chat_completions"]
        assert info["member_operations"] == ["chat"]
        assert info["test_operations"] == ["chat"]
        response = await admin.api.post(
            BASE + "/channel-addresses/resolve",
            json={
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
                "operations": ["chat"],
            },
        )
        assert response.status_code == 200, response.text
        target = response.json()
        assert target["directory_url"] == (root + prefix + "/models" if discovery else None)
        assert target["operation_targets"] == [
            {
                "operation": "chat",
                "method": "POST",
                "url": root + prefix + "/chat/completions",
                "outbound_protocol": "openai_compatible",
                "sdk_provider": "openai",
                "sdk_api_base": root + prefix,
                "sdk_expected_url": root + prefix + "/chat/completions",
            }
        ]
        assert (
            await member.api.post(
                BASE + "/channel-addresses/resolve",
                json={
                    "provider": provider_id,
                    "connection": {"address_mode": "provider_default"},
                    "operations": ["chat"],
                },
            )
        ).status_code == 403
    assert await counts(env) == before
    outbound.assert_not_awaited()


async def test_preset_save_registers_inventory_only_without_model_or_price(env, monkeypatch):
    admin = await env.client()
    outbound = AsyncMock(side_effect=AssertionError("saving must not read upstream models"))
    for adapter in PROVIDERS.values():
        monkeypatch.setattr(adapter, "list_models", outbound)
    for provider_id, (root, prefix, _) in PRESETS.items():
        response = await admin.api.post(
            BASE + "/channels",
            json={
                "name": "Fixture " + provider_id,
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
                "api_key": fake_key(provider_id),
                "models": [{"id": provider_id + "/fixture-model"}],
                "declared_apis": ["chat_completions"],
            },
        )
        assert response.status_code == 200, response.text
        row = response.json()
        assert row["provider"] == provider_id
        assert row["base_url"] == root + prefix
        assert row["connection"]["address_mode"] == "provider_default"
        assert row["credential_configured"] is True
        assert row["manual_enabled"] is True
        assert row["models"][0]["id"] == provider_id + "/fixture-model"
        assert row["models"][0]["source"] == "configuration"
        assert row["model_count"] == 1
        assert fake_key(provider_id) not in response.text
    assert (await counts(env))[:2] == (len(PRESETS), 0)
    outbound.assert_not_awaited()


async def test_unsupported_operations_and_missing_bearer_rejected_before_save(env):
    admin = await env.client()
    for provider_id in PRESETS:
        preview = await admin.api.post(
            BASE + "/channel-addresses/resolve",
            json={
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
                "operations": ["embedding"],
            },
        )
        assert preview.status_code == 422, preview.text
        rejected = await admin.api.post(
            BASE + "/channels",
            json={
                "name": "Unsupported",
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
                "api_key": "fake-only",
                "declared_apis": ["embeddings"],
            },
        )
        assert rejected.status_code == 422, rejected.text
        no_auth = await admin.api.post(
            BASE + "/channels",
            json={
                "name": "Missing bearer",
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
                "auth_mode": "none",
            },
        )
        assert no_auth.status_code == 422, no_auth.text
        missing_key = await admin.api.post(
            BASE + "/channels",
            json={
                "name": "No key",
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
            },
        )
        assert missing_key.status_code == 422, missing_key.text
    assert (await counts(env))[:2] == (0, 0)


@pytest.mark.parametrize(
    "provider_id,key",
    [("qwen-token-plan", "sk-ws-wrong-product"), ("qwen", "sk-sp-wrong-product")],
)
async def test_qwen_key_product_mismatch_is_actionable_without_io_or_secret_echo(
    env, monkeypatch, provider_id, key
):
    admin = await env.client()
    outbound = AsyncMock(side_effect=AssertionError("wrong product must not send a key"))
    monkeypatch.setattr(PROVIDERS[provider_id], "list_models", outbound)
    data = {
        "provider": provider_id,
        "connection": {"address_mode": "provider_default"},
        "api_key": key,
    }
    before = await counts(env)
    for path, body in (
        ("/channels", {**data, "name": "Wrong product"}),
        ("/channel-drafts/inspect", data),
    ):
        result = await admin.api.post(BASE + path, json=body)
        assert result.status_code == 422, result.text
        assert "套餐" in result.json()["error"]["message"]
        assert key not in result.text
    assert await counts(env) == before
    outbound.assert_not_awaited()


async def test_manual_directory_presets_draft_and_saved_checks_have_no_http(env, monkeypatch):
    from app.modules.llm.providers import openai_compatible

    admin = await env.client()

    def reject_http(*args, **kwargs):
        raise AssertionError("manual model registration must not make a metadata HTTP request")

    monkeypatch.setattr(openai_compatible, "resolve", reject_http)
    for provider_id in ("volcengine", "zhipu", "moonshot", "qwen", "qwen-token-plan"):
        draft = await admin.api.post(
            BASE + "/channel-drafts/inspect",
            json={
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
                "api_key": fake_key(provider_id),
                "discover": True,
            },
        )
        assert draft.status_code == 200, draft.text
        assert draft.json()["ok"] is False
        assert draft.json()["candidates"] == []
        assert "手动登记" in draft.json()["message"]
        created = await admin.api.post(
            BASE + "/channels",
            json={
                "name": "Manual " + provider_id,
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
                "api_key": fake_key(provider_id),
                "models": [{"id": "manually-registered"}],
            },
        )
        assert created.status_code == 200, created.text
        row = created.json()
        checked = await admin.api.post(
            BASE + "/channels/" + row["id"] + "/discover", json={"version": row["version"]}
        )
        assert checked.status_code == 200, checked.text
        assert checked.json()["ok"] is False
        assert checked.json()["candidates"] == []
        assert checked.json()["channel"]["models"][0]["id"] == "manually-registered"
        assert "手动登记" in checked.json()["message"]


async def test_registered_model_hint_uses_only_exact_provider_namespace(env, monkeypatch):
    from app.modules.llm.providers import model_hints

    metadata = {
        "zai/glm-fixture": {"litellm_provider": "zai", "mode": "chat"},
        "qwen_ai_platform/qwen-fixture": {
            "litellm_provider": "qwen_ai_platform",
            "mode": "chat",
        },
        "volcengine/volc-fixture": {"litellm_provider": "volcengine", "mode": "chat"},
        "moonshot/moon-fixture": {"litellm_provider": "moonshot", "mode": "chat"},
        "openai/overlap-fixture": {"litellm_provider": "openai", "mode": "chat"},
    }
    monkeypatch.setattr(model_hints.litellm, "model_cost", metadata)
    admin = await env.client()
    cases = [
        ("zhipu", "glm-fixture", "zai/glm-fixture"),
        ("qwen", "qwen-fixture", "qwen_ai_platform/qwen-fixture"),
        ("volcengine", "volc-fixture", "volcengine/volc-fixture"),
        ("moonshot", "moon-fixture", "moonshot/moon-fixture"),
        ("aihubmix", "overlap-fixture", None),
    ]
    for provider_id, upstream_id, expected_reference in cases:
        response = await admin.api.post(
            BASE + "/channels",
            json={
                "name": "Hints " + provider_id,
                "provider": provider_id,
                "connection": {"address_mode": "provider_default"},
                "api_key": fake_key(provider_id),
                "models": [{"id": upstream_id}],
            },
        )
        assert response.status_code == 200, response.text
        path = BASE + "/channels/" + response.json()["id"] + "/model-hint"
        hint = await admin.api.get(path, params={"model_id": upstream_id})
        assert hint.status_code == 200, hint.text
        assert hint.json()["reference_key"] == expected_reference
        assert hint.json()["kind"] == ("chat" if expected_reference else None)
        assert hint.json()["source"] == ("litellm" if expected_reference else "unknown")
        assert (await admin.api.get(path, params={"model_id": "unregistered"})).status_code == 404


@pytest.mark.parametrize("provider_id", ["qwen", "qwen-token-plan"])
async def test_saved_qwen_preset_diagnostic_reaches_existing_sdk_with_default_prefix(
    env, provider_id
):
    admin = await env.client()
    upstream = FastAPI()
    sent: list[tuple[str, str | None, dict]] = []

    @upstream.post("/{path:path}")
    async def respond(path: str, request: Request):
        sent.append((path, request.headers.get("authorization"), await request.json()))
        return {
            "id": "fixture-chat",
            "object": "chat.completion",
            "created": 1,
            "model": "qwen-fixture",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "local-response"},
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        created = await admin.api.post(
            BASE + "/channels",
            json={
                "name": "Qwen local fixture",
                "provider": provider_id,
                "connection": {"address_mode": "service_root", "service_root": root},
                "api_key": fake_key(provider_id),
                "models": [{"id": "qwen-fixture"}],
                "test_defaults": {
                    "upstream_id": "qwen-fixture",
                    "operation": "chat",
                    "endpoint": "chat_completions",
                    "stream": False,
                },
            },
        )
        assert created.status_code == 200, created.text
        row = created.json()
        assert row["base_url"] == root + "/compatible-mode/v1"
        assert row["test_defaults_status"] == {"valid": True, "reason": "ready"}
        request_id = str(uuid4())
        result = await admin.api.post(
            BASE + "/channels/" + row["id"] + "/diagnostics",
            json={
                "version": row["version"],
                "request_id": request_id,
                "upstream_id": "qwen-fixture",
                "operation": "chat",
                "endpoint": "chat_completions",
                "stream": False,
                "input": {"prompt": "local-prompt", "max_output_tokens": 8},
            },
        )
        assert result.status_code == 200, result.text
        assert result.json()["ok"] is True
        assert result.json()["request_id"] == request_id
        assert len(sent) == 1
        path, authorization, payload = sent[0]
        assert path == "compatible-mode/v1/chat/completions"
        assert authorization == "Bearer " + fake_key(provider_id)
        assert payload["model"] == "qwen-fixture"
        assert payload["messages"][0]["content"] == "local-prompt"
        assert (await counts(env))[:2] == (1, 0)
