"""Historical derived routes become stable explicit bindings without tenant expansion."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.llm.models import CatalogModel, ModelChannel
from app.modules.tenants.models import Tenant

spec = importlib.util.spec_from_file_location(
    "freeze_routes", Path("migrations/versions/102w_freeze_legacy_routes.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def channel(ident=None, **kwargs):
    return dict(
        id=ident or uuid4(),
        provider="openai-compatible",
        archived=False,
        declared_apis=["chat_completions"],
        models=[{"id": "vendor"}],
        routing={"model_mapping": {"public": "vendor"}, "priority": 8, "weight": 7},
        **kwargs,
    )


def test_no_legacy_source_is_exact_noop_and_current_binding_ids_prices_survive():
    model, cid, bid = map(str, [uuid4(), uuid4(), uuid4()])
    unchanged = {"operations": [], "marker": "keep"}
    assert module.freeze(model, unchanged, []) == unchanged
    old = {
        "slug": "public",
        "kind": "chat",
        "routing": {"source": "channels", "mode": "auto"},
        "bindings": [
            {
                "channel_id": cid,
                "upstream_id": "vendor",
                "enabled": False,
                "binding_id": bid,
                "procurement_price": {"marker": "retain"},
            }
        ],
    }
    result = module.freeze(model, old, [channel(cid)])
    binding = result["bindings"][0]
    assert binding["binding_id"] == bid and binding["enabled"] is False
    assert binding["procurement_price"] == {"marker": "retain"}
    assert binding["priority"] == 8 and binding["weight"] == 7
    assert "source" not in result["routing"] and old["routing"]["source"] == "channels"
    assert module.freeze(model, result, []) == result


def test_media_does_not_silently_choose_one_target():
    old = {"slug": "public", "kind": "speech", "routing": {"source": "channels"}}
    channels = [channel(), channel()]
    for row in channels:
        row["declared_apis"] = ["speech"]
    with pytest.raises(RuntimeError, match="select one historical media route"):
        module.freeze(str(uuid4()), old, channels)
    result = module.freeze(str(uuid4()), old, channels[:1])
    assert result["routing"] == {"mode": "fixed", "fallback": False}
    assert result["access"]["channel_id"] == str(channels[0]["id"])
    assert result["access"]["upstream_id"] == "vendor"


@pytest.mark.asyncio
async def test_upgrade_materializes_only_same_tenant_inventory_and_is_repeatable(monkeypatch):
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("explicit disposable database required")
    monkeypatch.setenv("ACTVERO_DATABASE_URL", url)
    monkeypatch.setenv("ACTVERO_PLATFORM_EDITION", "saas")
    schema = "test_freeze_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with owner.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    cfg = Config("alembic.ini")
    try:
        async with engine.begin() as conn:

            def upgrade(sync, target):
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, target)

            await conn.run_sync(upgrade, "101v_repository_consolidation")
            tenants, model_id, ids = [uuid4(), uuid4()], uuid4(), [uuid4(), uuid4()]
            for tenant in tenants:
                await conn.execute(Tenant.__table__.insert().values(id=tenant, name="same-name"))
            for tenant, cid in zip(tenants, ids, strict=True):
                await conn.execute(
                    ModelChannel.__table__.insert().values(
                        id=cid,
                        tenant_id=tenant,
                        provider="openai-compatible",
                        name="same-channel",
                        base_url="https://example.test/v1",
                        auth_mode="none",
                        models=[{"id": "vendor"}],
                        declared_apis=["chat_completions"],
                        routing=channel()["routing"],
                    )
                )
            original = {
                "slug": "public",
                "kind": "chat",
                "routing": {"source": "channels", "model_revision": "revision"},
            }
            await conn.execute(
                CatalogModel.__table__.insert().values(
                    id=model_id,
                    tenant_id=tenants[0],
                    slug="public",
                    name="public",
                    configuration=original,
                )
            )
            await conn.run_sync(upgrade, "head")
            value = await conn.scalar(
                text("SELECT configuration FROM llm_models WHERE id=:id"), {"id": model_id}
            )
            assert len(value["bindings"]) == 1 and value["bindings"][0]["channel_id"] == str(ids[0])
            assert value["bindings"][0]["binding_id"]
            await conn.run_sync(upgrade, "head")
            assert (
                await conn.scalar(
                    text("SELECT configuration FROM llm_models WHERE id=:id"), {"id": model_id}
                )
                == value
            )
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
