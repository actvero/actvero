"""Binding identity survives API edits and protects ownership in the isolated DB."""

from copy import deepcopy
from uuid import UUID

import pytest
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel

from app.modules.llm.binding_identity import legacy_binding_id
from app.modules.llm.models import CatalogModel

pytestmark = pytest.mark.asyncio
env = identity_env
BASE = "/api/v1/llm/models"


async def test_binding_ids_are_persisted_and_old_payload_reuses_identity(env) -> None:
    admin = await env.client()
    channel = await create_channel(admin, models=[{"id": "one"}, {"id": "two"}])
    created = await admin.api.post(
        BASE,
        json={
            "slug": "public-one",
            "name": "Public one",
            "access": {"enabled": False, "audience": "organization"},
            "operations": [
                {
                    "kind": "chat",
                    "budget_price": {"currency": "USD", "input": "1", "output": "2"},
                    "bindings": [{"channel_id": channel["id"], "upstream_id": "one"}],
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    model = created.json()
    first = model["operations"][0]["bindings"][0]
    assert first["binding_id"] and first["enabled"] is False
    assert model["bindings"][0]["binding_id"] == first["binding_id"]
    assert model["binding_states"][0]["binding_id"] == first["binding_id"]

    old_client = deepcopy(model)
    old_client["operations"][0]["bindings"][0].pop("binding_id")
    result = await admin.api.put(
        BASE + "/" + model["id"],
        json={
            "version": model["version"],
            "slug": model["slug"],
            "name": "Renamed",
            "operations": old_client["operations"],
        },
    )
    assert result.status_code == 200, result.text
    updated = result.json()
    assert updated["operations"][0]["bindings"][0]["binding_id"] == first["binding_id"]
    legacy_omission = await admin.api.put(
        BASE + "/" + model["id"],
        json={"version": updated["version"], "slug": updated["slug"], "name": "Legacy edit"},
    )
    assert legacy_omission.status_code == 200, legacy_omission.text
    updated = legacy_omission.json()
    assert updated["operations"][0]["bindings"] == updated["bindings"]
    assert updated["bindings"][0]["binding_id"] == first["binding_id"]
    assert updated["access"]["audience"] == "organization"
    assert updated["operations"][0]["budget_price"]["input"] == "1"
    async with env.sessions() as db:
        row = await db.get(CatalogModel, UUID(model["id"]))
        assert (
            row.configuration["operations"][0]["bindings"][0]["binding_id"] == first["binding_id"]
        )
        assert row.configuration["bindings"] == row.configuration["operations"][0]["bindings"]

    other = await admin.api.post(
        BASE,
        json={
            "slug": "another-public-name",
            "name": "Another public model",
            "operations": [
                {
                    "kind": "chat",
                    "bindings": [{"channel_id": channel["id"], "upstream_id": "one"}],
                }
            ],
        },
    )
    assert other.status_code == 200, other.text
    foreign_id = other.json()["operations"][0]["bindings"][0]["binding_id"]
    assert foreign_id != first["binding_id"]
    forged = await admin.api.put(
        BASE + "/" + model["id"],
        json={
            "version": updated["version"],
            "slug": updated["slug"],
            "name": "Forged",
            "operations": [
                {
                    "kind": "chat",
                    "bindings": [
                        {
                            "binding_id": foreign_id,
                            "channel_id": channel["id"],
                            "upstream_id": "one",
                        }
                    ],
                }
            ],
        },
    )
    assert forged.status_code == 409
    assert (await admin.api.get(BASE + "/" + model["id"])).json()["name"] == "Legacy edit"


async def test_old_json_detail_projects_id_without_writing(env) -> None:
    admin = await env.client()
    channel = await create_channel(admin, models=[{"id": "one"}])
    created = await admin.api.post(
        BASE,
        json={
            "slug": "old-json",
            "name": "Old",
            "bindings": [{"channel_id": channel["id"], "upstream_id": "one", "enabled": False}],
        },
    )
    assert created.status_code == 200, created.text
    model = created.json()
    async with env.sessions() as db:
        row = await db.get(CatalogModel, UUID(model["id"]))
        row.configuration["bindings"][0].pop("binding_id")
        row.configuration["operations"] = None
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(row, "configuration")
        await db.commit()
    before = (await admin.api.get(BASE + "/" + model["id"])).json()
    expected = legacy_binding_id(UUID(model["id"]), "chat", UUID(channel["id"]), "one")
    assert before["bindings"][0]["binding_id"] == str(expected)
    async with env.sessions() as db:
        row = await db.get(CatalogModel, UUID(model["id"]))
        assert "binding_id" not in row.configuration["bindings"][0]


@pytest.mark.parametrize("stored_operations", [False, True])
async def test_legacy_embedding_edit_omits_kind_without_changing_identity(
    env, stored_operations: bool
) -> None:
    admin = await env.client()
    channel = await create_channel(admin, models=[{"id": "embedding-upstream"}])
    binding = {
        "channel_id": channel["id"],
        "upstream_id": "embedding-upstream",
        "enabled": False,
    }
    initial = {
        "slug": "public-embedding",
        "name": "Embedding",
        "kind": "embedding",
        "bindings": [binding],
    }
    if stored_operations:
        initial["operations"] = [{"kind": "embedding", "bindings": [binding]}]
    created = await admin.api.post(BASE, json=initial)
    assert created.status_code == 200, created.text
    model = created.json()
    identity = model["bindings"][0]["binding_id"]
    path = BASE + "/" + model["id"]
    # Old clients send only the shared metadata, omitting kind, operations and bindings.
    renamed = await admin.api.put(
        path,
        json={"version": model["version"], "slug": model["slug"], "name": "Renamed"},
    )
    assert renamed.status_code == 200, renamed.text
    after = renamed.json()
    assert after["kind"] == "embedding" and after["bindings"][0]["binding_id"] == identity
    if stored_operations:
        assert after["operations"][0]["kind"] == "embedding"
        assert after["operations"][0]["bindings"][0]["binding_id"] == identity
    # The same client may include the old tuple without carrying binding_id.
    old_tuple = await admin.api.put(
        path,
        json={
            "version": after["version"],
            "slug": after["slug"],
            "name": "Tuple edit",
            "bindings": [{"channel_id": channel["id"], "upstream_id": "embedding-upstream"}],
        },
    )
    assert old_tuple.status_code == 200, old_tuple.text
    assert old_tuple.json()["kind"] == "embedding"
    assert old_tuple.json()["bindings"][0]["binding_id"] == identity
