"""Management resource migration preserves old facts and backfills read-only login grants."""

import json
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_management_resources_migration_preserves_all_old_tables_and_is_reversible():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_management_resources_migration_" + uuid4().hex
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

            await db.run_sync(migrate, "110e_client_downloads")
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
            await db.execute(
                text(
                    "INSERT INTO management_logins "
                    "(id,state_hash,nonce,challenge,redirect_uri,name,expires_at,"
                    "consumed,cancelled) "
                    "VALUES (:id,'state','nonce','challenge',"
                    "'http://127.0.0.1:49161/actvero/cli/callback','preserved',now(),false,false)"
                ),
                {"id": uuid4()},
            )
            old_tables = await db.run_sync(lambda sync: inspect(sync).get_table_names())
            old_tables.remove("alembic_version")

            async def snapshot():
                result = {}
                for table in old_tables:
                    projection = "to_jsonb(t)" + (
                        "- 'scope'" if table == "management_logins" else ""
                    )
                    rows = (
                        await db.execute(text(f'SELECT {projection} FROM "{table}" t'))
                    ).scalars()
                    result[table] = sorted(json.dumps(row, sort_keys=True) for row in rows)
                return result

            original = await snapshot()
            await db.run_sync(migrate, "112g_management_mcp_oauth")
            assert await db.scalar(text("SELECT version_num FROM alembic_version")) == (
                "112g_management_mcp_oauth"
            )
            assert await db.scalar(text("SELECT scope FROM management_logins")) == "management:read"
            tables = await db.run_sync(lambda sync: inspect(sync).get_table_names())
            assert set(tables) - set(old_tables) - {"alembic_version"} == {
                "management_commands",
                "management_mcp_oauth_attempts",
            }
            assert await snapshot() == original
            await db.run_sync(migrate, "112g_management_mcp_oauth")
            assert await snapshot() == original
            # Downgrade removes only the new receipt table and scope column.
            await db.run_sync(migrate, "110e_client_downloads", True)
            assert await snapshot() == original
            assert set(await db.run_sync(lambda sync: inspect(sync).get_table_names())) == (
                set(old_tables + ["alembic_version"])
            )
    finally:
        await engine.dispose()
        async with owner.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
