"""The new policy remains unset on upgrade and preserves existing installation data."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_cli_policy_upgrade_and_downgrade_preserve_installation():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_cli_settings_" + uuid4().hex
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

            await db.run_sync(migrate, "113h_management_merge")
            await db.execute(
                text("UPDATE installation SET platform_name = 'Preserved' WHERE id = 1")
            )
            before = (await db.execute(text("SELECT to_jsonb(i) FROM installation i"))).scalar_one()
            await db.run_sync(migrate, "114i_cli_settings")
            after = (await db.execute(text("SELECT to_jsonb(i) FROM installation i"))).scalar_one()
            assert after.pop("management_enabled") is None
            assert after == before
            await db.execute(text("UPDATE installation SET management_enabled = true"))
            await db.run_sync(migrate, "113h_management_merge", True)
            assert (
                await db.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one() == before
    finally:
        await engine.dispose()
        async with owner.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
