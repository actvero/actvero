"""Brand upgrades preserve every pre-existing row and the original logo UUID/bytes."""

import io
import json
import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from PIL import Image
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_brand_migration_preserves_old_data_and_original_asset():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_brand_migration_" + uuid4().hex
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

            await db.run_sync(migrate, "110e_client_downloads")
            image = io.BytesIO()
            Image.new("RGBA", (256, 256), (8, 20, 50, 130)).save(image, format="WEBP")
            original_id = uuid4()
            await db.execute(
                text(
                    "UPDATE installation SET platform_name=:name, platform_logo_data=:data, "
                    "platform_logo_version=:id"
                ),
                {"name": "Preserved", "data": image.getvalue(), "id": original_id},
            )
            tables = await db.run_sync(lambda sync: inspect(sync).get_table_names())
            tables.remove("alembic_version")
            original_columns = await db.run_sync(
                lambda sync: {
                    table: [column["name"] for column in inspect(sync).get_columns(table)]
                    for table in tables
                }
            )

            async def snapshot():
                result = {}
                for table in tables:
                    rows = (
                        await db.execute(text(f'SELECT to_jsonb(t) FROM "{table}" t'))
                    ).scalars()
                    normalized = []
                    for row in rows:
                        preserved = {column: row[column] for column in original_columns[table]}
                        normalized.append(json.dumps(preserved, sort_keys=True))
                    result[table] = sorted(normalized)
                return result

            before = await snapshot()
            await db.run_sync(migrate, "head")
            assert before == await snapshot()
            asset = (await db.execute(text("SELECT id,data,media_type FROM brand_assets"))).one()
            assert (
                asset.id == original_id
                and asset.data == image.getvalue()
                and asset.media_type == "image/webp"
            )
            assert await db.scalar(text("SELECT branding_assets FROM installation")) == {
                "mark_light": str(original_id)
            }
            assert (
                await db.scalar(text("SELECT identity_branding_revision FROM installation")) is None
            )
            await db.run_sync(migrate, "head")
            assert before == await snapshot()
            assert await db.scalar(text("SELECT count(*) FROM brand_assets")) == 1
    finally:
        await engine.dispose()
        async with owner.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
