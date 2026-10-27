"""Either migration branch upgrades without altering existing release records."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "start", ["120o_quota_assignments", "118m_release_provenance", "119n_download_only_releases"]
)
async def test_gateway_and_distribution_histories_merge_without_losing_data(start):
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_gateway_distribution_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    async with owner.begin() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as db:

            def migrate(sync, revision):
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, revision)

            await db.run_sync(migrate, start)
            ident = uuid4()
            await db.execute(
                text(
                    "INSERT INTO client_releases "
                    "(id,version,release_date,notes,assets,status,revision) "
                    "VALUES (:id,'1.0.0',CURRENT_DATE,'preserved','[]','published',1)"
                ),
                {"id": ident},
            )
            before = await db.scalar(
                text("SELECT to_jsonb(r) FROM client_releases r WHERE id=:id"), {"id": ident}
            )
            await db.run_sync(migrate, "head")
            assert await db.scalar(text("SELECT version_num FROM alembic_version")) == (
                "121p_gateway_distribution"
            )
            assert (
                await db.scalar(
                    text("SELECT to_jsonb(r) FROM client_releases r WHERE id=:id"), {"id": ident}
                )
                == before
            )
            tables = await db.run_sync(lambda sync: set(inspect(sync).get_table_names()))
            assert {
                "client_distributions",
                "newapi_model_directories",
                "quota_assignments",
            } <= tables
            columns = await db.run_sync(lambda sync: inspect(sync).get_columns("model_channels"))
            assert any(column["name"] == "snapshot_partial" for column in columns)
    finally:
        await engine.dispose()
        async with owner.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
