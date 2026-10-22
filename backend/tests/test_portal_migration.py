"""Upgrades preserve every existing installation field and saved portal policy."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_portal_migration_preserves_installation_and_saved_policy():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_portal_" + uuid4().hex
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

            await conn.run_sync(upgrade, "107b_desktop_discovery")
            await conn.execute(
                text(
                    "UPDATE installation SET platform_name='Preserved', "
                    "platform_logo_data='\\x0102', platform_mail_ciphertext='sealed'"
                )
            )
            before = (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one()
            await conn.run_sync(upgrade, "head")
            after = (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one()
            assert after.pop("portal_enabled") is False
            assert after.pop("branding_assets") == {}
            assert after.pop("identity_branding_revision") is None
            assert {column: after[column] for column in before} == before
            await conn.execute(text("UPDATE installation SET portal_enabled=true"))
            await conn.run_sync(upgrade, "head")
            again = (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one()
            assert again.pop("portal_enabled") is True
            assert again.pop("branding_assets") == {}
            assert again.pop("identity_branding_revision") is None
            assert {column: again[column] for column in before} == before
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
