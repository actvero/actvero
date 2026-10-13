"""Versioned channel controls and actor-scoped create receipts in isolated PostgreSQL."""

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_llm_channels import create as legacy_create

from app.modules.audit.models import AuditEvent
from app.modules.llm.channel_management import default_status
from app.modules.llm.models import ModelCall, ModelChannel, MutationReceipt
from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.base import ModelListing
from app.modules.llm.schemas import TestDefaults as ChannelTestDefaults
from app.modules.llm.schemas import UpstreamModel

pytestmark = pytest.mark.asyncio
env = identity_env
BASE = "/api/v1/llm/channels"


async def test_defaults_receipt_replay_and_secret_digest(env) -> None:
    admin = await env.client()
    request_id = uuid4()
    body = {
        "request_id": str(request_id),
        "name": "Receipt channel",
        "base_url": "https://example.com/v1",
        "api_key": "fake-api-key-one",
    }
    first = await admin.api.post(BASE, json=body)
    assert first.status_code == 200, first.text
    created = first.json()
    assert created["manual_enabled"] is True
    assert created["automatic_protection"] == {"enabled": True}
    assert created["test_defaults"] is None
    assert created["connection"]["address_mode"] == "legacy_api_base"
    assert created["routing_version"] == 1
    receipt_url = "/api/v1/llm/mutation-receipts/" + str(request_id)
    receipt = await admin.api.get(receipt_url, params={"scope": "channel.create"})
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["resource_id"] == created["id"]
    repeated = await admin.api.post(BASE, json=body)
    assert repeated.status_code == 200 and repeated.json()["id"] == created["id"]
    conflict = await admin.api.post(BASE, json=body | {"api_key": "fake-api-key-two"})
    assert conflict.status_code == 409
    member = await env.client(role="member", tenant=admin.tenant)
    assert (
        await member.api.get(receipt_url, params={"scope": "channel.create"})
    ).status_code == 403
    other_admin = await env.client(tenant=admin.tenant)
    assert (
        await other_admin.api.get(receipt_url, params={"scope": "channel.create"})
    ).status_code == 404
    different_tenant = await env.client()
    assert (
        await different_tenant.api.get(receipt_url, params={"scope": "channel.create"})
    ).status_code == 404
    assert (await admin.api.get(receipt_url, params={"scope": "other"})).status_code == 404
    async with env.sessions() as db:
        rows = list(await db.scalars(select(MutationReceipt)))
        assert len(rows) == 1
        assert rows[0].payload_digest != body["api_key"]
        assert len(rows[0].payload_digest) == 64
        assert body["api_key"] not in str(rows[0].__dict__)
        assert (await db.scalar(select(func.count()).select_from(ModelChannel))) == 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "llm.channel.create")
            )
        ) == 1


async def test_new_address_survives_old_editor_and_routing_version_tracks_target(env) -> None:
    admin = await env.client()
    created = await admin.api.post(
        BASE,
        json={
            "name": "Official",
            "provider": "openai",
            "connection": {"address_mode": "provider_default"},
            "api_key": "fake-official-key",
            "models": [{"id": "gpt-example"}],
            "manual_enabled": False,
            "automatic_protection": {"enabled": False},
            "test_defaults": {
                "upstream_id": "gpt-example",
                "operation": "chat",
                "endpoint": "chat_completions",
                "stream": False,
            },
        },
    )
    assert created.status_code == 200, created.text
    row = created.json()
    assert row["base_url"] == "https://api.openai.com/v1"
    assert row["connection"]["address_mode"] == "provider_default"
    path = BASE + "/" + row["id"]
    old_editor = await admin.api.put(
        path,
        json={
            "version": row["version"],
            "name": "Renamed official",
            "base_url": row["base_url"],
        },
    )
    assert old_editor.status_code == 200, old_editor.text
    edited = old_editor.json()
    assert edited["connection"]["address_mode"] == "provider_default"
    assert edited["routing_version"] == row["routing_version"]
    assert edited["manual_enabled"] is False
    assert edited["automatic_protection"] == {"enabled": False}
    assert edited["test_defaults"]["upstream_id"] == "gpt-example"
    target = {
        "version": edited["version"],
        "name": "Changed target",
        "provider": "openai",
        "connection": {"address_mode": "service_root", "service_root": "https://proxy.example"},
    }
    assert (await admin.api.put(path, json=target)).status_code == 422
    changed = await admin.api.put(path, json=target | {"api_key": "fake-replacement-key"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["routing_version"] == row["routing_version"] + 1
    assert changed.json()["connection"]["address_mode"] == "service_root"


async def test_saved_test_default_validates_and_source_removal_marks_invalid(env) -> None:
    admin = await env.client()
    row = await legacy_create(admin, models=[{"id": "source-one"}])
    path = BASE + "/" + row["id"]
    bad = await admin.api.put(
        path,
        json={
            "version": row["version"],
            "test_defaults": {
                "upstream_id": "missing",
                "operation": "chat",
                "endpoint": "chat_completions",
                "stream": False,
            },
        },
    )
    assert bad.status_code == 422
    good = await admin.api.put(
        path,
        json={
            "version": row["version"],
            "test_defaults": {
                "upstream_id": "source-one",
                "operation": "chat",
                "endpoint": "chat_completions",
                "stream": False,
            },
        },
    )
    assert good.status_code == 200, good.text
    assert good.json()["test_defaults_status"] == {"valid": True, "reason": "ready"}
    chat_stream = await admin.api.put(
        path,
        json={
            "version": good.json()["version"],
            "test_defaults": {
                "upstream_id": "source-one",
                "operation": "chat",
                "endpoint": "chat_completions",
                "stream": True,
            },
        },
    )
    assert chat_stream.status_code == 200, chat_stream.text
    assert chat_stream.json()["test_defaults_status"] == {"valid": True, "reason": "ready"}
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ModelCall)) == 0
    removed = await admin.api.request(
        "DELETE",
        path + "/models",
        json={"version": chat_stream.json()["version"], "models": [{"id": "source-one"}]},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["test_defaults"]["upstream_id"] == "source-one"
    assert removed.json()["test_defaults_status"] == {"valid": False, "reason": "model_missing"}


async def test_stream_defaults_preserve_validation_order_and_only_chat_is_ready() -> None:
    registered = [{"id": "source-one"}]
    declared = ["chat_completions", "embeddings", "rerank", "images"]

    def reason(operation: str, endpoint: str, upstream_id: str = "source-one") -> str:
        value = ChannelTestDefaults.model_validate(
            {
                "upstream_id": upstream_id,
                "operation": operation,
                "endpoint": endpoint,
                "stream": True,
            }
        )
        status = default_status(
            value,
            provider_id="openai-compatible",
            declared_apis=declared,
            models=registered,
        )
        assert status is not None
        return status.reason

    assert reason("chat", "chat_completions") == "ready"
    assert reason("chat", "chat_completions", "missing") == "model_missing"
    assert reason("chat", "embeddings") == "endpoint_unsupported"
    assert reason("embedding", "embeddings") == "stream_unsupported"
    assert reason("rerank", "rerank") == "stream_unsupported"
    assert reason("image_generation", "images") == "stream_unsupported"
    assert reason("speech", "speech") == "stream_unsupported"
    unsupported = ChannelTestDefaults(
        upstream_id="source-one", operation="chat", endpoint="chat_completions", stream=True
    )
    status = default_status(
        unsupported,
        provider_id="unknown",
        declared_apis=declared,
        models=registered,
    )
    assert status is not None and status.reason == "operation_unsupported"
    status = default_status(
        unsupported,
        provider_id="openai-compatible",
        declared_apis=[],
        models=registered,
    )
    assert status is not None and status.reason == "endpoint_unsupported"


async def test_status_batch_filters_and_archive_preserves_manual_intent(env) -> None:
    admin = await env.client()
    first = await legacy_create(admin, name="One")
    second = await legacy_create(admin, name="Two")
    result = await admin.api.post(
        BASE + "/status-batch",
        json={
            "items": [
                {"id": first["id"], "version": first["version"], "manual_enabled": False},
                {"id": second["id"], "version": 99, "manual_enabled": False},
                {"id": str(uuid4()), "version": 1, "manual_enabled": False},
            ]
        },
    )
    assert result.status_code == 200, result.text
    assert [item["status"] for item in result.json()["items"]] == [
        "updated",
        "conflict",
        "not_found",
    ]
    filtered = (await admin.api.get(BASE, params={"manual_enabled": False})).json()
    assert filtered["total"] == 1 and filtered["items"][0]["id"] == first["id"]
    assert filtered["items"][0]["health_summary"]["state"] == "no_routes"
    assert (await admin.api.get(BASE, params={"provider": "unknown"})).json()["total"] == 0
    archived = await admin.api.put(
        BASE + "/" + first["id"] + "/archive",
        json={"version": result.json()["items"][0]["version"], "archived": True},
    )
    assert archived.status_code == 200
    assert archived.json()["manual_enabled"] is False
    restored = await admin.api.put(
        BASE + "/" + first["id"] + "/archive",
        json={"version": archived.json()["version"], "archived": False},
    )
    assert restored.status_code == 200 and restored.json()["manual_enabled"] is False
    assert (await admin.api.get(BASE, params={"health_summary": "no_routes"})).json()["total"] == 2


async def test_new_connection_is_forwarded_to_draft_and_saved_directory(env, monkeypatch) -> None:
    admin = await env.client()
    listing = AsyncMock(return_value=ModelListing([UpstreamModel(id="model-one")]))
    monkeypatch.setattr(PROVIDERS["openai"], "list_models", listing)
    draft = await admin.api.post(
        "/api/v1/llm/channel-drafts/inspect",
        json={
            "provider": "openai",
            "connection": {"address_mode": "provider_default"},
            "api_key": "fake-key",
            "discover": True,
        },
    )
    assert draft.status_code == 200, draft.text
    assert listing.await_args.kwargs["connection"]["address_mode"] == "provider_default"
    created = await admin.api.post(
        BASE,
        json={
            "name": "Forwarded",
            "provider": "openai",
            "connection": {"address_mode": "provider_default"},
            "api_key": "fake-key",
        },
    )
    assert created.status_code == 200, created.text
    saved = await admin.api.post(
        BASE + "/" + created.json()["id"] + "/check",
        json={"version": created.json()["version"]},
    )
    assert saved.status_code == 200, saved.text
    assert listing.await_args.kwargs["connection"]["address_mode"] == "provider_default"


async def test_concurrent_create_request_id_has_one_resource_and_audit(env) -> None:
    admin = await env.client()
    body = {
        "request_id": str(uuid4()),
        "name": "Concurrent receipt",
        "base_url": "https://example.com/v1",
        "api_key": "fake-key",
    }
    first, second = await asyncio.gather(
        admin.api.post(BASE, json=body), admin.api.post(BASE, json=body)
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ModelChannel)) == 1
        assert await db.scalar(select(func.count()).select_from(MutationReceipt)) == 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "llm.channel.create")
            )
            == 1
        )


async def test_status_batch_requires_admin_csrf_and_at_most_fifty(env) -> None:
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    row = await legacy_create(admin)
    path = BASE + "/status-batch"
    body = {"items": [{"id": row["id"], "version": row["version"], "manual_enabled": False}]}
    assert (await member.api.post(path, json=body)).status_code == 403
    assert (
        await admin.api.post(path, json=body, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    assert (await admin.api.post(path, json={"items": body["items"] * 51})).status_code == 422
    assert (await admin.api.get(BASE + "/" + row["id"])).json()["manual_enabled"] is True


async def test_new_gemini_rejects_unencodable_registered_target(env) -> None:
    admin = await env.client()
    payload = {
        "name": "Gemini target",
        "provider": "gemini",
        "connection": {"address_mode": "provider_default"},
        "api_key": "fake-key",
    }
    create_bad = await admin.api.post(BASE, json=payload | {"models": [{"id": "models/foo"}]})
    assert create_bad.status_code == 422
    assert "models/" in create_bad.json()["error"]["message"]
    created = await admin.api.post(BASE, json=payload)
    assert created.status_code == 200, created.text
    path = BASE + "/" + created.json()["id"]
    register_bad = await admin.api.post(
        path + "/models",
        json={"version": created.json()["version"], "models": [{"id": "models/foo"}]},
    )
    assert register_bad.status_code == 422
    update_bad = await admin.api.put(
        path,
        json={
            "version": created.json()["version"],
            "models": [{"id": "models/foo"}],
        },
    )
    assert update_bad.status_code == 422
    assert (await admin.api.get(path)).json()["models"] == []
