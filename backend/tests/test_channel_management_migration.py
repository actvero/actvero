"""Real Alembic upgrade preserves legacy destinations and health evidence."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.llm.catalog_schemas import CatalogInput, ModelBinding
from app.modules.llm.models import ModelChannel
from app.modules.llm.providers.connection import (
    ChannelConnection,
    legacy_connection,
    resolve_connection,
)
from app.modules.llm.routing import credential_fingerprint, fingerprint, hash_value
from app.modules.tenants.models import Tenant


def test_channel_downgrade_requires_preserving_idempotency_and_manual_state():
    spec = importlib.util.spec_from_file_location(
        "channel_migration", Path("migrations/versions/94o_channel_management.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="幂等回执"):
        module.downgrade()


@pytest.mark.asyncio
async def test_legacy_channel_upgrade_preserves_all_old_columns_targets_and_fingerprints():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_channel_migration_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    async with owner.begin() as connection:
        await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:

            def upgrade(sync, revision):
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, revision)

            await connection.run_sync(upgrade, "93n_model_binding_ids")
            tenant_id = uuid4()
            await connection.execute(
                Tenant.__table__.insert().values(id=tenant_id, name="保留组织"),
            )
            for index, (provider, base) in enumerate(
                [
                    ("openai-compatible", "https://example.com/proxy/v1"),
                    ("openai", "https://api.openai.com/v1"),
                    ("anthropic", "https://example.com/proxy"),
                    ("gemini", "https://example.com/v1beta"),
                    ("deepseek", "https://api.deepseek.com"),
                    ("siliconflow", "https://api.siliconflow.cn/v1"),
                ]
            ):
                await connection.execute(
                    sa.text(
                        "INSERT INTO model_channels "
                        "(id, tenant_id, provider, name, description, icon, base_url, auth_mode, "
                        "sealed_key, timeout_seconds, declared_apis, archived, version, models, "
                        "checks, snapshot, snapshot_id, snapshot_at, created_at) VALUES "
                        "(:id, :tenant, :provider, :name, '保留说明', '', :base, 'api_key', "
                        ":sealed, 31, '[\"chat_completions\"]', :archived, :version, "
                        '\'[{"id":"original-model","source":"manual"}]\', '
                        '\'[{"message":"保留目录记录"}]\', \'["original-model"]\', '
                        ":snapshot, now(), now())"
                    ),
                    {
                        "id": uuid4(),
                        "tenant": tenant_id,
                        "provider": provider,
                        "name": f"保留渠道-{index}",
                        "base": base,
                        "sealed": f"fixture-only-ciphertext-{index}",
                        "archived": index == 2,
                        "version": index + 4,
                        "snapshot": uuid4(),
                    },
                )
            await connection.execute(
                sa.text(
                    "INSERT INTO llm_route_health "
                    "(id,tenant_id,fingerprint,tested_at,failures,"
                    "cooldown_until,probe_until,blocked) "
                    "VALUES ('old-health', :tenant, 'old-fingerprint', now(), 2, "
                    "now() + interval '1 hour', now() + interval '1 minute', true)"
                ),
                {"tenant": tenant_id},
            )
            before = list(
                (await connection.execute(sa.text("SELECT to_jsonb(c) FROM model_channels c")))
                .scalars()
                .all()
            )
            health = await connection.scalar(sa.text("SELECT to_jsonb(h) FROM llm_route_health h"))
            await connection.run_sync(upgrade, "head")
            after = {
                row["id"]: row
                for row in (
                    await connection.execute(sa.text("SELECT to_jsonb(c) FROM model_channels c"))
                ).scalars()
            }
            for old in before:
                saved = after[old["id"]]
                assert {key: saved[key] for key in old} == old
                assert saved["manual_enabled"] is True
                assert saved["automatic_protection"] == {"enabled": True}
                assert saved["test_defaults"] is None
                assert saved["snapshot_partial"] is None
                assert saved["routing_version"] == old["version"]
                assert saved["connection"] == {
                    "address_mode": "legacy_api_base",
                    "legacy_base_url": old["base_url"],
                    "resolver_version": 1,
                }
                for stream in (False, True):
                    assert resolve_connection(
                        old["provider"],
                        legacy_connection(old["base_url"]),
                        operations=("chat",) if stream else None,
                        stream=stream,
                    ) == resolve_connection(
                        old["provider"],
                        ChannelConnection(**saved["connection"]),
                        operations=("chat",) if stream else None,
                        stream=stream,
                    )
                # Keep the old fingerprint algorithm as the expected value,
                # independently of the runtime's new routing_version fallback.
                config = CatalogInput(slug="stable", name="保留模型")
                binding = ModelBinding(channel_id=old["id"], upstream_id="original-model")
                channel = ModelChannel(**saved)
                old_hash = hash_value(
                    [
                        config.kind,
                        config.retrieval.model_dump(),
                        config.capabilities.model_dump(),
                        [o.model_dump() for o in config.reasoning_options],
                        binding.chat_options.model_dump(exclude={"limits"}),
                        (config.context_window, config.max_output),
                        config.routing.model_revision,
                        binding.compatibility_key,
                        binding.upstream_id,
                        old["version"],
                        credential_fingerprint(channel),
                    ]
                )
                assert fingerprint(config, binding, channel) == old_hash
            saved_health = await connection.scalar(
                sa.text("SELECT to_jsonb(h) FROM llm_route_health h")
            )
            assert {key: saved_health[key] for key in health} == health
            assert saved_health["block_reason"] is None
            assert saved_health["health_generation"] == 0
    finally:
        await engine.dispose()
        async with owner.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
