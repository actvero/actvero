"""96q adds guarded health state while preserving every prior row."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


def test_protection_downgrade_refuses_to_drop_health():
    spec = importlib.util.spec_from_file_location(
        "protection_migration", Path("migrations/versions/96q_route_protection.py")
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="保护状态不能自动丢弃"):
        module.downgrade()


@pytest.mark.asyncio
async def test_upgrade_preserves_old_blocked_lease_and_future_cooldown(monkeypatch):
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    monkeypatch.setenv("ACTVERO_DATABASE_URL", url)
    schema = "test_protection_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    async with owner.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as conn:

            def upgrade(sync, target):
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, target)

            await conn.run_sync(upgrade, "95p_diagnostic_calls")
            tenant = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO tenants (id, name, active, created_at) "
                    "VALUES (:id, 'preserved', true, now())"
                ),
                {"id": tenant},
            )
            await conn.execute(
                text("""
                INSERT INTO llm_route_health
                    (id, tenant_id, fingerprint, tested_at, failures,
                     cooldown_until, probe_until, blocked)
                VALUES ('old', :tenant, 'old-fingerprint', now(), 3,
                        now() + interval '2 days', now() + interval '20 seconds', true)
            """),
                {"tenant": tenant},
            )
            before = await conn.scalar(text("SELECT to_jsonb(h) FROM llm_route_health h"))
            await conn.run_sync(upgrade, "head")
            after = await conn.scalar(text("SELECT to_jsonb(h) FROM llm_route_health h"))
            assert after.pop("block_reason") is None
            assert after.pop("health_generation") == 0
            assert after == before
            for statement, constraint in [
                (
                    "UPDATE llm_route_health SET block_reason='invented'",
                    "ck_llm_route_block_reason",
                ),
                ("UPDATE llm_route_health SET health_generation=-1", "ck_llm_route_generation"),
            ]:
                with pytest.raises(IntegrityError, match=constraint):
                    async with conn.begin_nested():
                        await conn.execute(text(statement))
            await conn.execute(
                text(
                    "UPDATE llm_route_health SET health_generation=2147483648, "
                    "block_reason='unclassified_rejection'"
                )
            )
            assert (
                await conn.scalar(text("SELECT health_generation FROM llm_route_health"))
                == 2147483648
            )
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
