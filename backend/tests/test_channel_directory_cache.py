"""Persisted directories remain scoped to the saved connection and administrator."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from test_identity_access import env as identity_env
from test_llm_channels import BASE, create

from app.modules.auth.service import now
from app.modules.llm.models import ModelChannel
from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.base import ModelListing
from app.modules.llm.schemas import UpstreamModel
from app.modules.tenants.models import Tenant

env = identity_env
pytestmark = pytest.mark.asyncio
DRAFT = "/api/v1/llm/channel-drafts/inspect"


@pytest.fixture
def upstream(monkeypatch):
    mock = AsyncMock(return_value=ModelListing([UpstreamModel(id="model-a")], partial=True))
    monkeypatch.setattr(PROVIDERS["openai-compatible"], "list_models", mock)
    return mock


async def fetch(admin, row):
    result = await admin.api.post(
        DRAFT, json={"channel_id": row["id"], "version": row["version"], "discover": True}
    )
    assert result.status_code == 200, result.text
    return result.json()


async def test_editor_cache_survives_reads_metadata_edits_and_old_snapshot_registration(
    env, upstream
):
    admin = await env.client()
    row = await create(admin)
    path = BASE + "/" + row["id"]
    assert row["model_directory"] is None
    result = await fetch(admin, row)
    directory = result["model_directory"]
    assert directory["candidates"] == [{"id": "model-a"}]
    assert directory["partial"] is True
    for _ in range(2):
        detail = (await admin.api.get(path)).json()
        assert detail["model_directory"] == directory
        assert detail["version"] == 1 and detail["models"] == []
    saved = await admin.api.put(
        path,
        json={
            "version": 1,
            "name": "New name",
            "description": "New description",
            "manual_enabled": False,
            "timeout_seconds": 30,
            "declared_apis": ["chat_completions", "embeddings"],
            "models": [{"id": "manual-model"}],
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["model_directory"] == directory
    async with env.sessions() as db:
        stored = await db.get(ModelChannel, UUID(row["id"]))
        stored.snapshot_at = now() - timedelta(days=7)
        await db.commit()
    registered = await admin.api.post(
        path + "/models",
        json={"version": 2, "snapshot_id": directory["snapshot_id"], "models": [{"id": "model-a"}]},
    )
    assert registered.status_code == 200, registered.text
    assert registered.json()["model_directory"]["snapshot_id"] == directory["snapshot_id"]
    assert registered.json()["model_count"] == 2
    upstream.assert_awaited_once()


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "https://changed.example/v1", "api_key": "replacement-key"},
        {"api_key": "replacement-key"},
        {"auth_mode": "none"},
    ],
)
async def test_connection_or_credential_changes_invalidate_cache(env, upstream, changes):
    admin = await env.client()
    row = await create(admin)
    directory = (await fetch(admin, row))["model_directory"]
    path = BASE + "/" + row["id"]
    result = await admin.api.put(path, json={"version": 1, **changes})
    assert result.status_code == 200, result.text
    assert result.json()["model_directory"] is None
    stale = await admin.api.post(
        path + "/models",
        json={"version": 2, "snapshot_id": directory["snapshot_id"], "models": [{"id": "model-a"}]},
    )
    assert stale.status_code == 409


async def test_failed_refresh_retains_cache_and_successful_empty_refresh_replaces_it(env, upstream):
    admin = await env.client()
    row = await create(admin)
    directory = (await fetch(admin, row))["model_directory"]
    path = BASE + "/" + row["id"]
    upstream.side_effect = HTTPException(502, "Unavailable")
    assert not (await fetch(admin, row))["ok"]
    failed = (await admin.api.post(path + "/discover", json={"version": 1})).json()
    assert not failed["ok"] and failed["channel"]["model_directory"] == directory
    upstream.side_effect = None
    upstream.return_value = ModelListing([])
    empty = (await admin.api.post(path + "/discover", json={"version": 2})).json()
    cached = empty["channel"]["model_directory"]
    assert empty["ok"] and cached["candidates"] == [] and cached["partial"] is False
    assert cached["snapshot_id"] != directory["snapshot_id"]
    assert (await admin.api.get(path)).json()["model_directory"] == cached


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "https://unsaved.example/v1", "api_key": "temporary-key"},
        {"api_key": "temporary-key"},
        {"auth_mode": "none"},
    ],
)
async def test_unsaved_connection_preview_cannot_replace_saved_cache(env, upstream, changes):
    admin = await env.client()
    row = await create(admin)
    directory = (await fetch(admin, row))["model_directory"]
    upstream.return_value = ModelListing([UpstreamModel(id="temporary-model")])
    result = await admin.api.post(
        DRAFT, json={"channel_id": row["id"], "version": 1, "discover": True, **changes}
    )
    assert result.status_code == 200, result.text
    assert result.json()["model_directory"] is None
    assert result.json()["candidates"] == [{"id": "temporary-model"}]
    assert (await admin.api.get(BASE + "/" + row["id"])).json()["model_directory"] == directory


async def test_cached_directory_is_not_exposed_to_members_or_other_organizations(env, upstream):
    admin = await env.client()
    row = await create(admin)
    await fetch(admin, row)
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    async with env.sessions() as db:
        # This disposable fixture starts with the community single-tenant guard.
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        tenant = Tenant(name="Other organization")
        db.add(tenant)
        await db.flush()
        foreign = ModelChannel(
            tenant_id=tenant.id,
            provider="openai-compatible",
            name="Foreign channel",
            base_url="https://foreign.example/v1",
            auth_mode="none",
        )
        db.add(foreign)
        await db.commit()
    for client, channel_id, status in [
        (member, row["id"], 403),
        (outsider, row["id"], 403),
        (admin, str(foreign.id), 404),
    ]:
        result = await client.api.get(BASE + "/" + channel_id)
        assert result.status_code == status and "model-a" not in result.text
        result = await client.api.post(
            DRAFT, json={"channel_id": channel_id, "version": 1, "discover": True}
        )
        assert result.status_code == status and "model-a" not in result.text
    upstream.assert_awaited_once()


async def test_inflight_draft_cannot_cache_results_after_connection_changes(env, upstream):
    admin = await env.client()
    other = await env.client(tenant=admin.tenant)
    row = await create(admin)
    await fetch(admin, row)
    started, finish = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await finish.wait()
        return ModelListing([UpstreamModel(id="stale-model")])

    upstream.side_effect = slow
    pending = asyncio.create_task(
        admin.api.post(DRAFT, json={"channel_id": row["id"], "version": 1, "discover": True})
    )
    await asyncio.wait_for(started.wait(), 5)
    path = BASE + "/" + row["id"]
    try:
        changed = await other.api.put(path, json={"version": 1, "api_key": "new-key"})
        assert changed.status_code == 200
    finally:
        finish.set()
    assert (await pending).status_code == 409
    assert (await admin.api.get(path)).json()["model_directory"] is None
