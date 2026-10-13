"""Only auditable replacements become historical; packages and explicit bans stay intact."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_adoption_migration_only_recovers_proven_replacements():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_adoption_upgrade_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    async with owner.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as conn:

            def upgrade(sync, revision):
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, revision)

            await conn.run_sync(upgrade, "104y_device_session_policy")
            tenant, user, skill = uuid4(), uuid4(), uuid4()
            await conn.execute(
                text("INSERT INTO tenants (id,name,active) VALUES (:id,'kept',true)"),
                {"id": tenant},
            )
            await conn.execute(
                text("INSERT INTO users (id,name) VALUES (:id,'kept')"), {"id": user}
            )
            await conn.execute(
                text(
                    "INSERT INTO skill_categories "
                    "(tenant_id,id,name,name_key,position,revision) VALUES "
                    "(:id,'uncategorized','未分类','kept',0,1)"
                ),
                {"id": tenant},
            )
            await conn.execute(
                text(
                    "INSERT INTO skills "
                    "(id,tenant_id,name,display_name,description,category,audience,member_ids,"
                    "revision,created_at,icon_selection) VALUES "
                    "(:id,:tenant,'kept','kept','kept','uncategorized','organization','[]',"
                    '1,now(),\'{"source":"auto"}\')'
                ),
                {"id": skill, "tenant": tenant},
            )
            version_ids = []
            for index in range(4):
                vid = uuid4()
                version_ids.append(vid)
                await conn.execute(
                    text(
                        "INSERT INTO skill_versions "
                        "(id,skill_id,version,status,release_notes,uploader_name,sha256,size,files,"
                        "skill_md,created_at,published_at,package_icon,icon_warning) VALUES "
                        "(:id,:skill,:version,:status,'notes','kept',:sha,9,'[]',"
                        "'immutable',now(),now(),'','')"
                    ),
                    {
                        "id": vid,
                        "skill": skill,
                        "version": str(index),
                        "status": "published" if index == 3 else "withdrawn",
                        "sha": "a" * 64,
                    },
                )
                await conn.execute(
                    text("INSERT INTO skill_packages (version_id,data) VALUES (:id,:data)"),
                    {"id": vid, "data": b"unchanged"},
                )
            await conn.execute(
                text("UPDATE skills SET default_version_id=:id WHERE id=:skill"),
                {"id": version_ids[3], "skill": skill},
            )
            # 0 known replacement; 1 replacement followed by explicit stop; 2 unknown old status.
            for version, replacement, age in (("0", True, -2), ("1", True, -2), ("1", False, -1)):
                await conn.execute(
                    text(
                        "INSERT INTO audit_events "
                        "(id,tenant_id,actor_id,actor_name,action,target_id,target_name,result,"
                        "details,created_at) VALUES (:id,:tenant,:user,'kept','skills.withdraw',"
                        ":skill,'kept','success',cast(:details AS json),"
                        "now()+:age*interval '1 hour')"
                    ),
                    {
                        "id": uuid4(),
                        "tenant": tenant,
                        "user": user,
                        "skill": skill,
                        "age": age,
                        "details": '{"version":"'
                        + version
                        + '"'
                        + (',"replaced_by":"3"' if replacement else "")
                        + "}",
                    },
                )
            before = (
                (
                    await conn.execute(
                        text("SELECT to_jsonb(v) FROM skill_versions v ORDER BY version")
                    )
                )
                .scalars()
                .all()
            )
            packages = (
                await conn.execute(
                    text("SELECT version_id,data FROM skill_packages ORDER BY version_id")
                )
            ).all()
            await conn.run_sync(upgrade, "105z_resource_adoptions")
            after = (
                (
                    await conn.execute(
                        text("SELECT to_jsonb(v) FROM skill_versions v ORDER BY version")
                    )
                )
                .scalars()
                .all()
            )
            assert [v["status"] for v in after] == [
                "superseded",
                "withdrawn",
                "withdrawn",
                "published",
            ]
            for index, (old, current) in enumerate(zip(before, after, strict=True)):
                if index == 0:
                    current["status"] = old["status"]
                assert current == old
            assert (
                await conn.execute(
                    text("SELECT version_id,data FROM skill_packages ORDER BY version_id")
                )
            ).all() == packages
            assert await conn.scalar(text("SELECT count(*) FROM resource_adoptions")) == 0
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
