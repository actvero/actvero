"""Display names do not rename routes or change member access."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_gateway_publication_access import setup
from test_identity_access import env as identity_env
from test_model_gateway import bind
from test_model_gateway_models import BASE, model
from test_repository_isolation import organizations

from app.modules.llm.models import CatalogModel
from app.modules.model_gateway import client

env = identity_env
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("method", ["post", "put"])
async def test_display_name_can_be_saved_without_channels_prices_or_publication(
    env, monkeypatch, method
):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    bind(env, admin)
    row = model()
    writes = []

    async def native(request, tenant, verb, path, **kwargs):
        assert tenant == admin.tenant.id
        if verb != "GET":
            writes.append(deepcopy(kwargs["payload"]))
            row.update(kwargs["payload"])
        if path == "/api/models/":
            return {"items": [deepcopy(row)], "total": 1} if verb == "GET" else deepcopy(row)
        assert path == "/api/models/21"
        return deepcopy(row)

    monkeypatch.setattr(client, "call", native)
    path = BASE + "/api/models/"
    detail = (await admin.api.get(path + "21")).json()["data"]
    headers = {"If-Match": detail["revision"]} if method == "put" else {}
    body = {
        "id": 21,
        "model_name": row["model_name"],
        "name_rule": 0,
        "display_name": " 团队快速模型 ",
    }
    assert (await getattr(member.api, method)(path, json=body, headers=headers)).status_code == 403
    assert (
        await getattr(admin.api, method)(path, json=body, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    assert not writes
    response = await getattr(admin.api, method)(path, json=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["display_name"] == "团队快速模型"
    assert writes == [{k: v for k, v in body.items() if k != "display_name"}]
    page = (await admin.api.get(path)).json()["data"]["items"][0]
    assert page["display_name"] == "团队快速模型"
    async with env.sessions() as db:
        saved = await db.scalar(select(CatalogModel))
        assert saved.slug == row["model_name"] and saved.name == "团队快速模型"
        assert not saved.configuration["access"]["enabled"]
        assert saved.configuration["access"]["audience"] == "administrators"
    # An earlier metadata snapshot cannot overwrite the new name.
    count = len(writes)
    stale = await admin.api.put(
        path, json=body | {"display_name": "旧页面"}, headers={"If-Match": detail["revision"]}
    )
    assert stale.status_code == 409 and len(writes) == count


async def test_rename_and_clear_preserve_member_resource_access_and_invocation_id(env, monkeypatch):
    admin, draft, channels, _, previous = await setup(env, monkeypatch)
    member = await env.client(role="member", tenant=admin.tenant)
    assert (await admin.api.put("/api/v1/model-gateway/publication", json=draft)).status_code == 200
    row = model(model_name="team")
    writes = []

    async def native(request, tenant, method, path, **kwargs):
        if path in {"/api/models/21", "/api/models/"}:
            if method == "PUT":
                writes.append(deepcopy(kwargs["payload"]))
                row.update(kwargs["payload"])
            return deepcopy(row)
        return await previous(request, tenant, method, path, **kwargs)

    monkeypatch.setattr(client, "call", native)
    path = BASE + "/api/models/"
    catalog_path = "/api/v1/account/llm/models"
    before = (await member.api.get(catalog_path)).json()["items"][0]
    async with env.sessions() as db:
        saved = await db.scalar(select(CatalogModel))
        resource, config = saved.id, deepcopy(saved.configuration)
    original_channels = deepcopy(channels)
    for display, expected in [("团队深度模型", "团队深度模型"), ("", "team")]:
        detail = (await admin.api.get(path + "21")).json()["data"]
        response = await admin.api.put(
            path,
            json={"id": 21, "model_name": "team", "name_rule": 0, "display_name": display},
            headers={"If-Match": detail["revision"]},
        )
        assert response.status_code == 200, response.text
        async with env.sessions() as db:
            saved = await db.get(CatalogModel, resource)
            assert saved.name == expected and saved.slug == "team"
            assert saved.configuration == {**config, "name": expected}
        after = (await member.api.get(catalog_path)).json()["items"][0]
        assert after["name"] == expected and after["slug"] == "team"
        assert after["resource"] == before["resource"]
        assert channels == original_channels
        assert writes[-1] == {"id": 21, "model_name": "team", "name_rule": 0}


@pytest.mark.parametrize("display", [None, {"name": "bad"}, "x" * 101, "line\nbreak"])
async def test_invalid_names_are_rejected_before_native_writes(env, monkeypatch, display):
    admin = await env.client()
    bind(env, admin)
    native = AsyncMock()
    monkeypatch.setattr(client, "call", native)
    response = await admin.api.post(
        BASE + "/api/models/", json={"model_name": "team", "display_name": display}
    )
    assert response.status_code == 422
    native.assert_not_awaited()


async def test_failed_native_save_does_not_leave_a_display_name(env, monkeypatch):
    admin = await env.client()
    bind(env, admin)
    monkeypatch.setattr(client, "call", AsyncMock(side_effect=HTTPException(502, "unavailable")))
    response = await admin.api.post(
        BASE + "/api/models/", json={"model_name": "team", "display_name": "团队模型"}
    )
    assert response.status_code == 502
    async with env.sessions() as db:
        assert await db.scalar(select(CatalogModel)) is None


async def test_display_names_are_scoped_to_the_authenticated_organization(env, monkeypatch):
    admin, second = await organizations(env)
    bind(env, admin)
    connection = env.provider.settings.newapi_connections[0].model_copy(
        update={"tenant_id": second.tenant.id, "base_url": "https://second.example"}
    )
    env.provider.settings.newapi_connections.append(connection)
    native = AsyncMock(return_value=model())
    monkeypatch.setattr(client, "call", native)
    body = {"model_name": model()["model_name"], "display_name": "First organization model"}
    assert (await admin.api.post(BASE + "/api/models/", json=body)).status_code == 200
    first = (await admin.api.get(BASE + "/api/models/21")).json()["data"]
    foreign = (await second.api.get(BASE + "/api/models/21")).json()["data"]
    assert first["display_name"] == body["display_name"]
    assert foreign["display_name"] == "" and foreign["revision"] != first["revision"]


async def test_metadata_without_an_override_does_not_require_a_publishable_id(env, monkeypatch):
    admin = await env.client()
    bind(env, admin)
    native = AsyncMock(return_value=model(model_name="metadata*only"))
    monkeypatch.setattr(client, "call", native)
    response = await admin.api.post(
        BASE + "/api/models/", json={"model_name": "metadata*only", "display_name": ""}
    )
    assert response.status_code == 200, response.text
    assert native.await_args.kwargs["payload"] == {"model_name": "metadata*only"}
    async with env.sessions() as db:
        assert await db.scalar(select(CatalogModel)) is None
