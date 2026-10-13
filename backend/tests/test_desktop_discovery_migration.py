"""Existing installation data is identical, new namespace survives repeat upgrade."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_discovery_upgrade_preserves_installation_and_stable_namespace():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_discovery_" + uuid4().hex
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

            await conn.run_sync(upgrade, "106a_dependency_commands")
            await conn.execute(
                text(
                    "UPDATE installation SET platform_name='Preserved', "
                    "platform_logo_data='\\x0102', platform_mail_ciphertext='sealed'"
                )
            )
            before = (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one()
            await conn.run_sync(upgrade, "107b_desktop_discovery")
            after = (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one()
            identity, revision = after.pop("instance_id"), after.pop("branding_revision")
            assert after == before
            await conn.run_sync(upgrade, "107b_desktop_discovery")
            again = (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one()
            assert again["instance_id"] == identity and again["branding_revision"] == revision
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
