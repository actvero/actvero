"""Address previews enforce console access and never contact or modify channels."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel

from app.modules.llm.providers import PROVIDERS

env = identity_env
pytestmark = pytest.mark.asyncio
PATH = "/api/v1/llm/channel-addresses/resolve"
BODY = {
    "provider": "openai-compatible",
    "connection": {"address_mode": "service_root", "service_root": "https://example.com/proxy/"},
    "operations": ["chat", "embedding"],
}


async def snapshot(env):
    async with env.sessions() as db:
        return {
            table: list((await db.execute(text(f'SELECT to_jsonb(t) FROM "{table}" t'))).scalars())
            for table in ("model_channels", "llm_models", "llm_route_health", "audit_events")
        }


async def test_preview_returns_paths_without_upstream_or_business_mutations(env, monkeypatch):
    admin = await env.client()
    await create_channel(admin)
    before = await snapshot(env)
    outbound = AsyncMock(side_effect=AssertionError("preview must not read model inventory"))
    for adapter in PROVIDERS.values():
        monkeypatch.setattr(adapter, "list_models", outbound)
    response = await admin.api.post(PATH, json=BODY)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["directory_url"] == "https://example.com/proxy/v1/models"
    assert [target["url"] for target in value["operation_targets"]] == [
        "https://example.com/proxy/v1/chat/completions",
        "https://example.com/proxy/v1/embeddings",
    ]
    assert value["warnings"] == []
    assert "test-secret" not in response.text
    assert await snapshot(env) == before
    outbound.assert_not_awaited()

    # A private origin can be previewed but is not authorized for actual execution.
    response = await admin.api.post(
        PATH,
        json=BODY
        | {
            "connection": {
                "address_mode": "legacy_api_base",
                "legacy_base_url": "http://127.0.0.1:9999/proxy/v1/",
            }
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["directory_url"] == "http://127.0.0.1:9999/proxy/v1/models"
    assert response.json()["warnings"] == ["legacy_base_preserved"]
    outbound.assert_not_awaited()


async def test_preview_requires_admin_session_and_csrf(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    assert (await member.api.post(PATH, json=BODY)).status_code == 403
    assert (
        await admin.api.post(PATH, json=BODY, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    admin.api.cookies.clear()
    # The existing mutation dependency rejects an absent CSRF session first.
    assert (await admin.api.post(PATH, json=BODY)).status_code == 403


async def test_invalid_address_inputs_never_echo_secrets(env):
    admin = await env.client()
    invalid = [
        BODY | {"api_key": "must-not-echo"},
        BODY
        | {
            "connection": {
                "address_mode": "service_root",
                "service_root": "https://user:must-not-echo@example.com",
            }
        },
        BODY
        | {
            "connection": {
                "address_mode": "service_root",
                "service_root": "https://example.com?key=must-not-echo",
            }
        },
        BODY
        | {
            "connection": {"address_mode": "service_root", "service_root": "https://example.com/v1"}
        },
        BODY | {"connection": {"address_mode": "provider_default"}},
        BODY | {"operations": ["chat", "chat"]},
        BODY | {"stream": True},
        BODY
        | {
            "connection": {
                "address_mode": "service_root",
                "service_root": "https://example.com",
                "api_prefix": "//evil.example/v1",
            }
        },
        BODY
        | {
            "connection": {
                "address_mode": "legacy_api_base",
                "legacy_base_url": "https://example.com/v1",
                "resolver_version": 2,
            }
        },
        BODY | {"provider": "gemini", "model": "../bad", "operations": ["chat"]},
    ]
    for payload in invalid:
        response = await admin.api.post(PATH, json=payload)
        assert response.status_code == 422, response.text
        assert "must-not-echo" not in response.text
