"""Model facts remain independent of native pricing and member publication."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_gateway_publication_access import setup
from test_identity_access import env as identity_env
from test_model_gateway import bind
from test_model_gateway_models import BASE as NATIVE
from test_model_gateway_models import model
from test_repository_isolation import organizations

from app.modules.llm.models import CatalogModel
from app.modules.model_gateway import client
from app.modules.model_gateway.models import GatewayModelParameters

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/model-gateway/parameters"
FACTS = {
    "version": 0,
    "capability_mode": "manual",
    "context_window": 64000,
    "max_output": 8000,
    "capabilities": {"tools": "unknown"},
    "reference_model": "reference-only",
    "source": {"provider": "administrator"},
}


async def test_facts_save_without_routes_prices_or_publication_and_enforce_versions(
    env, monkeypatch
):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    native = AsyncMock(side_effect=HTTPException(502, "offline"))
    monkeypatch.setattr(client, "call", native)
    path = BASE + "?model=unknown-model"
    assert (await member.api.put(path, json=FACTS)).status_code == 403
    assert (
        await admin.api.put(path, json=FACTS, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    response = await admin.api.put(path, json=FACTS)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["version"] == 1
    assert (await admin.api.put(path, json=FACTS)).status_code == 409
    native.assert_not_awaited()
    editor_data = (await admin.api.get(path + "&include_reference=false")).json()["data"]
    assert editor_data["context_window"] == 64000
    assert "automatic" not in editor_data and "sources" not in editor_data
    native.assert_not_awaited()
    async with env.sessions() as db:
        assert await db.scalar(select(CatalogModel)) is None
        saved = await db.scalar(select(GatewayModelParameters))
        assert saved.configuration["context_window"] == 64000
        assert "chat_policy" not in saved.configuration
    data = (await admin.api.get(path)).json()["data"]
    assert data["context_window"] == 64000
    assert data["automatic"]["status"] == "unavailable"


async def test_facts_and_native_metadata_share_save_without_forwarding_private_fields(
    env, monkeypatch
):
    admin = await env.client()
    bind(env, admin)
    native = AsyncMock(return_value=model(model_name="team"))
    monkeypatch.setattr(client, "call", native)
    body = {
        "model_name": "team",
        "name_rule": 0,
        "display_name": "团队模型",
        "actvero_parameters": FACTS,
    }
    response = await admin.api.post(NATIVE + "/api/models/", json=body)
    assert response.status_code == 200, response.text
    assert native.await_args.kwargs["payload"] == {"model_name": "team", "name_rule": 0}
    async with env.sessions() as db:
        saved = await db.scalar(select(CatalogModel))
        assert saved.name == "团队模型"
        assert saved.configuration["context_window"] == 64000
        assert not saved.configuration["access"]["enabled"]
        facts = await db.scalar(select(GatewayModelParameters))
        assert facts.model_name == "team" and facts.version == 1
    native.reset_mock()
    bad = await admin.api.post(
        NATIVE + "/api/models/", json=body | {"actvero_parameters": FACTS | {"max_output": 128000}}
    )
    assert bad.status_code in {409, 422}
    native.assert_not_awaited()


async def test_usage_cannot_overwrite_facts_and_facts_preserve_usage_policy(env, monkeypatch):
    admin, draft, _, _, native = await setup(env, monkeypatch)
    path = BASE + "?model=team"
    assert (await admin.api.put(path, json=FACTS)).status_code == 200
    summary = (await admin.api.get("/api/v1/model-gateway/publication?model=team")).json()["data"]
    assert summary["version"] == 0 and summary["context_window"] == 64000
    assert summary["capability_mode"] == "manual"
    native.reset_mock()
    response = await admin.api.put(
        "/api/v1/model-gateway/publication",
        json=draft
        | {
            "context_window": 1000000,
            "max_output": 256000,
            "chat_policy": {"default_max_output": 2000},
        },
    )
    assert response.status_code == 200, response.text
    async with env.sessions() as db:
        row = await db.scalar(select(CatalogModel))
        original = deepcopy(row.configuration)
        assert original["context_window"] == 64000
        assert original["chat_policy"]["default_max_output"] == 2000
    native.reset_mock()
    response = await admin.api.put(path, json=FACTS | {"version": 1, "context_window": 96000})
    assert response.status_code == 200, response.text
    native.assert_not_awaited()
    async with env.sessions() as db:
        row = await db.scalar(select(CatalogModel))
        assert row.configuration["access"] == original["access"]
        assert row.configuration["chat_policy"] == original["chat_policy"]
        assert row.configuration["context_window"] == 96000
    # Reject contradictory model facts before any native metadata mutation.
    response = await admin.api.post(
        NATIVE + "/api/models/",
        json={
            "model_name": "team",
            "actvero_parameters": FACTS | {"version": 2, "max_output": 1000},
        },
    )
    assert response.status_code == 409
    native.assert_not_awaited()


async def test_facts_are_scoped_to_active_organization(env):
    first, second = await organizations(env)
    path = BASE + "?model=same-model"
    assert (await first.api.put(path, json=FACTS)).status_code == 200
    assert (await second.api.put(path, json=FACTS | {"context_window": 96000})).status_code == 200
    async with env.sessions() as db:
        one = await db.get(GatewayModelParameters, (first.tenant.id, "same-model"))
        two = await db.get(GatewayModelParameters, (second.tenant.id, "same-model"))
        assert one.configuration["context_window"] == 64000
        assert two.configuration["context_window"] == 96000


async def test_archived_publication_reuses_identity_and_facts_after_channel_replacement(
    env, monkeypatch
):
    admin, draft, channels, _, _ = await setup(env, monkeypatch)
    assert (await admin.api.put(BASE + "?model=team", json=FACTS)).status_code == 200
    path = "/api/v1/model-gateway/publication"
    assert (await admin.api.put(path, json=draft)).status_code == 200
    async with env.sessions() as db:
        row = await db.scalar(select(CatalogModel))
        resource, version = row.id, row.version
        row.archived = True
        await db.commit()
    channels[:] = [channels[0] | {"id": 2, "name": "Replacement"}]
    response = await admin.api.put(path, json=draft | {"version": version})
    assert response.status_code == 200, response.text
    async with env.sessions() as db:
        row = await db.scalar(select(CatalogModel))
        assert row.id == resource and not row.archived
        assert row.configuration["context_window"] == 64000
        assert row.configuration["access"]["enabled"]
        assert len((await db.scalars(select(GatewayModelParameters))).all()) == 1
