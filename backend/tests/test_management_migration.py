"""Management migration adds only independent tables; old facts are preserved."""

import json
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_management_migration_preserves_all_old_tables_and_is_reversible():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_management_migration_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    async with owner.begin() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as db:

            def migrate(sync, revision, downgrade=False):
                cfg.attributes["connection"] = sync
                (command.downgrade if downgrade else command.upgrade)(cfg, revision)

            await db.run_sync(migrate, "108c_site_portal")
            user_id, identity_id = uuid4(), uuid4()
            await db.execute(
                text("INSERT INTO users (id,name) VALUES (:id,'preserved')"), {"id": user_id}
            )
            await db.execute(
                text(
                    "INSERT INTO login_identities (id,user_id,issuer,subject,email_verified) "
                    "VALUES (:id,:uid,'https://identity.test','preserved',true)"
                ),
                {"id": identity_id, "uid": user_id},
            )
            old_tables = await db.run_sync(lambda sync: inspect(sync).get_table_names())
            old_tables.remove("alembic_version")

            async def snapshot():
                result = {}
                for table in old_tables:
                    rows = (
                        await db.execute(text(f'SELECT to_jsonb(t) FROM "{table}" t'))
                    ).scalars()
                    result[table] = sorted(json.dumps(row, sort_keys=True) for row in rows)
                return result

            original = await snapshot()
            await db.run_sync(migrate, "109d_management_cli")
            assert await db.scalar(text("SELECT version_num FROM alembic_version")) == (
                "109d_management_cli"
            )
            tables = await db.run_sync(lambda sync: inspect(sync).get_table_names())
            assert set(tables) - set(old_tables) - {"alembic_version"} == {
                "management_sessions",
                "management_tokens",
                "management_logins",
            }
            assert await snapshot() == original
            await db.run_sync(migrate, "109d_management_cli")
            assert await snapshot() == original
            # Only our three tables are dropped; no old session/auth/resource tables change.
            await db.run_sync(migrate, "108c_site_portal", True)
            assert await snapshot() == original
            assert set(await db.run_sync(lambda sync: inspect(sync).get_table_names())) == (
                set(old_tables + ["alembic_version"])
            )
    finally:
        await engine.dispose()
        async with owner.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
