"""Pinned SDK hints are advisory and never grant capabilities or call upstreams."""

from uuid import uuid4

import pytest
from test_identity_access import env as identity_env
from test_llm_channels import BASE, create

from app.modules.llm.providers.model_hints import model_hint

env = identity_env


def test_image_hint_requires_enabled_channel_interface():
    known = model_hint("openai", "dall-e-3", ["images"])
    assert known.kind == "image_generation" and known.available_kinds == ["image_generation"]
    assert model_hint("openai", "dall-e-3", ["chat_completions"]).kind is None
    unknown = model_hint("openai-compatible", "opaque-image", ["images"])
    assert unknown.kind is None and unknown.available_kinds == ["image_generation"]


@pytest.mark.parametrize(
    ("provider", "name", "mode", "kind"),
    [
        ("openai", "gpt-4o", "chat", "chat"),
        ("openai", "text-embedding-3-small", "embedding", "embedding"),
        ("openai", "dall-e-3", "image_generation", None),
        ("gemini", "gemini-embedding-001", "embedding", None),
        ("deepseek", "deepseek-chat", "chat", "chat"),
        ("anthropic", "gpt-4o", None, None),
        ("openai", "GPT-4O", None, None),
        ("openai", "gpt-4o-made-up", None, None),
        ("openai-compatible", "text-embedding-3-small", None, None),
        ("siliconflow", "BAAI/bge-m3", None, None),
    ],
)
def test_exact_provider_metadata_does_not_imply_integration(
    provider, name, mode, kind, monkeypatch
):
    def no_network(*args, **kwargs):
        pytest.fail("Metadata hint must not contact upstream")

    monkeypatch.setattr("socket.create_connection", no_network)
    hint = model_hint(provider, name, ["chat_completions", "embeddings", "rerank"])
    assert hint.mode == mode
    assert hint.kind == kind
    assert hint.source == ("litellm" if mode else "unknown")
    if provider == "gemini":
        assert hint.available_kinds == ["chat"]
    assert model_hint("openai", "text-embedding-3-small", ["chat_completions"]).kind is None


@pytest.mark.asyncio
async def test_hint_requires_admin_registered_model_and_current_channel(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    row = await create(
        admin,
        provider="openai",
        models=[{"id": "text-embedding-3-small"}],
        declared_apis=["embeddings"],
    )
    path = BASE + "/" + row["id"]
    result = await admin.api.get(
        path + "/model-hint", params={"model_id": "text-embedding-3-small"}
    )
    assert result.status_code == 200, result.text
    assert result.json()["kind"] == "embedding"
    assert "price" not in result.text and "test-secret" not in result.text
    refreshed = (await admin.api.get(path)).json()
    assert {k: v for k, v in refreshed.items() if k != "health_summary"} == {
        k: v for k, v in row.items() if k != "health_summary"
    }
    assert refreshed["health_summary"]["state"] == "no_routes"
    assert (
        await member.api.get(path + "/model-hint?model_id=text-embedding-3-small")
    ).status_code == 403
    assert (await admin.api.get(path + "/model-hint?model_id=gpt-4o")).status_code == 404
    assert (
        await admin.api.get(BASE + "/" + str(uuid4()) + "/model-hint?model_id=gpt-4o")
    ).status_code == 404
    assert (
        await admin.api.put(path + "/archive", json={"version": row["version"], "archived": True})
    ).status_code == 200
    assert (
        await admin.api.get(path + "/model-hint?model_id=text-embedding-3-small")
    ).status_code == 409
    admin.api.cookies.clear()
    assert (
        await admin.api.get(path + "/model-hint?model_id=text-embedding-3-small")
    ).status_code == 401
