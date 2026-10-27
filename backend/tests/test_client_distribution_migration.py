"""Upgrade and downgrade preserve existing download records in a disposable schema."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_distribution_migration_preserves_downloads_and_indexes(monkeypatch):
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    monkeypatch.setenv("ACTVERO_DATABASE_URL", url)
    schema = "test_distribution_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    async with owner.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as db:

            def migrate(sync, revision, down=False):
                cfg.attributes["connection"] = sync
                (command.downgrade if down else command.upgrade)(cfg, revision)

            await db.run_sync(migrate, "116k_model_timeouts")
            ident = uuid4()
            await db.execute(
                text(
                    "INSERT INTO client_releases "
                    "(id,version,release_date,notes,assets,status,revision) "
                    "VALUES (:id,'1.0.0',CURRENT_DATE,'keep','[]','published',1)"
                ),
                {"id": ident},
            )
            before = await db.scalar(
                text("SELECT to_jsonb(r) FROM client_releases r WHERE id=:id"), {"id": ident}
            )
            await db.run_sync(migrate, "117l_client_distribution")
            storage_id = uuid4()
            await db.execute(
                text(
                    "INSERT INTO client_storage "
                    "(id,name,endpoint,region,bucket,prefix,public_url,path_style,credentials,"
                    "enabled,is_default,revision) "
                    "VALUES (:id,'old','https://s3.example.com','r1','bucket','old-prefix',"
                    "'https://files.example.com',false,'sealed-fixture',true,true,3)"
                ),
                {"id": storage_id},
            )
            await db.execute(
                text(
                    "INSERT INTO client_artifacts "
                    "(id,release_id,target,role,filename,source,url,storage_id,object_key,"
                    "status,range_supported,validation,created_at) "
                    "VALUES (:id,:release,'win-x64','payload','old.exe','upload',"
                    "'https://files.example.com/old-prefix/old.exe',:storage,"
                    "'old-prefix/old.exe','ready',true,'{}',CURRENT_TIMESTAMP)"
                ),
                {"id": uuid4(), "release": ident, "storage": storage_id},
            )
            old_storage = await db.scalar(
                text("SELECT to_jsonb(s) FROM client_storage s WHERE id=:id"), {"id": storage_id}
            )
            await db.run_sync(migrate, "118m_release_provenance")
            assert (
                await db.scalar(
                    text("SELECT to_jsonb(r) FROM client_releases r WHERE id=:id"), {"id": ident}
                )
                == before
            )
            migrated_storage = await db.scalar(
                text("SELECT to_jsonb(s) FROM client_storage s WHERE id=:id"), {"id": storage_id}
            )
            assert migrated_storage.pop("locator_frozen") is True
            assert migrated_storage == old_storage
            source_columns = await db.run_sync(
                lambda sync: inspect(sync).get_columns("client_distributions")
            )
            assert any(c["name"] == "source_commit" for c in source_columns)
            indexes = await db.run_sync(lambda sync: inspect(sync).get_indexes("client_artifacts"))
            assert any(i["column_names"] == ["release_id"] for i in indexes)
            columns = await db.run_sync(
                lambda sync: inspect(sync).get_columns("management_sessions")
            )
            assert any(c["name"] == "platform_permissions" for c in columns)
            await db.run_sync(migrate, "116k_model_timeouts", True)
            assert (
                await db.scalar(
                    text("SELECT to_jsonb(r) FROM client_releases r WHERE id=:id"), {"id": ident}
                )
                == before
            )
            await db.run_sync(migrate, "118m_release_provenance")
    finally:
        await engine.dispose()
        async with owner.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
