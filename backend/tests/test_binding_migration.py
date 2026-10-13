"""Frozen ID backfill preserves prior JSON, health and resource identity."""

import importlib.util
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from test_identity_access import env as identity_env

from app.modules.llm.models import CatalogModel, RouteHealth

env = identity_env


def migration():
    spec = importlib.util.spec_from_file_location(
        "binding_migration", Path("migrations/versions/93n_model_binding_ids.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def strip_ids(config):
    result = deepcopy(config)
    for part in [result, *(result.get("operations") or [])]:
        for binding in part.get("bindings", []):
            binding.pop("binding_id", None)
    return result


def test_frozen_backfill_is_stable_nonmutating_and_operation_scoped():
    module = migration()
    model_id, channel_id = uuid4(), uuid4()
    binding = {"channel_id": str(channel_id), "upstream_id": "model-a", "enabled": True}
    original = {
        "kind": "chat",
        "bindings": [deepcopy(binding)],
        "operations": [
            {"kind": "chat", "bindings": [deepcopy(binding)], "enabled": False},
            {"kind": "embedding", "bindings": [deepcopy(binding)]},
        ],
        "marker": {"do_not_normalize": "0.00200"},
    }
    snapshot = deepcopy(original)
    result = module.backfill_configuration(model_id, original)
    assert original == snapshot
    assert strip_ids(result) == original
    root = result["bindings"][0]["binding_id"]
    assert root == result["operations"][0]["bindings"][0]["binding_id"]
    assert root != result["operations"][1]["bindings"][0]["binding_id"]
    assert module.backfill_configuration(model_id, result) == result
    from app.modules.llm.binding_identity import legacy_binding_id

    assert root == str(legacy_binding_id(model_id, "chat", channel_id, "model-a"))
    assert module.backfill_configuration(uuid4(), original)["bindings"][0]["binding_id"] != root


def test_downgrade_requires_explicit_data_preservation():
    with pytest.raises(RuntimeError, match="稳定绑定身份"):
        migration().downgrade()


@pytest.mark.asyncio
async def test_postgres_backfill_preserves_rows_versions_and_health(env):
    admin = await env.client()
    channel_id, model_id = uuid4(), uuid4()
    binding = {
        "channel_id": str(channel_id),
        "upstream_id": "old-model",
        "enabled": True,
        "priority": 7,
        "price": {"input": "0.0200", "currency": "USD"},
    }
    config = {
        "name": "保留模型",
        "slug": "keep-public-id",
        "bindings": [deepcopy(binding)],
        "kind": "chat",
        "access": {"enabled": True, "audience": "organization"},
        "operations": [{"kind": "chat", "enabled": True, "bindings": [deepcopy(binding)]}],
    }
    async with env.sessions() as db:
        db.add(
            CatalogModel(
                id=model_id,
                tenant_id=admin.tenant.id,
                slug="keep-public-id",
                name="保留模型",
                configuration=config,
                version=12,
            )
        )
        db.add(
            RouteHealth(
                id="a" * 64,
                tenant_id=admin.tenant.id,
                fingerprint="b" * 64,
                failures=2,
                blocked=True,
            )
        )
        await db.commit()
        before_model = await db.scalar(
            text("SELECT to_jsonb(t) FROM llm_models t WHERE id=:id"), {"id": model_id}
        )
        before_health = list(
            (await db.execute(text("SELECT to_jsonb(t) FROM llm_route_health t"))).scalars()
        )
        await db.rollback()
    async with env.app.state.database.engine.begin() as connection:

        def upgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                migration().upgrade()

        await connection.run_sync(upgrade)
    async with env.sessions() as db:
        after_model = await db.scalar(
            text("SELECT to_jsonb(t) FROM llm_models t WHERE id=:id"), {"id": model_id}
        )
        assert strip_ids(after_model["configuration"]) == before_model["configuration"]
        assert {k: v for k, v in after_model.items() if k != "configuration"} == {
            k: v for k, v in before_model.items() if k != "configuration"
        }
        assert (
            list((await db.execute(text("SELECT to_jsonb(t) FROM llm_route_health t"))).scalars())
            == before_health
        )
        saved = await db.scalar(select(CatalogModel).where(CatalogModel.id == model_id))
        assert saved.configuration["bindings"][0]["binding_id"]
