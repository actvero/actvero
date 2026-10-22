"""Consent migration preserves business records and closes historical write grants."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_cli_consent_migration_preserves_read_sessions_and_requires_new_write_approval():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_cli_consent_" + uuid4().hex
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

            await db.run_sync(migrate, "114i_cli_settings")
            user, identity, read, write = (uuid4() for _ in range(4))
            await db.execute(
                text("INSERT INTO users (id,name) VALUES (:id,'Preserved')"), {"id": user}
            )
            await db.execute(
                text(
                    "INSERT INTO login_identities (id,user_id,issuer,subject,email_verified) "
                    "VALUES (:id,:uid,'https://identity.example.com','preserved',true)"
                ),
                {"id": identity, "uid": user},
            )
            for session_id, scope in [
                (read, "management:read"),
                (write, "management:read management:write"),
            ]:
                await db.execute(
                    text(
                        "INSERT INTO management_sessions (id,identity_id,client_id,scope,name,"
                        "authenticated_at,created_at,last_active_at,expires_at,"
                        "absolute_expires_at) "
                        "VALUES (:id,:identity,'actvero-cli',:scope,'Saved CLI',"
                        "now(),now(),now(),now()+interval '1 day',now()+interval '30 day')"
                    ),
                    {"id": session_id, "identity": identity, "scope": scope},
                )
            await db.run_sync(migrate, "head")
            rows = (
                await db.execute(
                    text("SELECT id,revoked_at,authorized_org_ids FROM management_sessions")
                )
            ).all()
            by_id = {row.id: row for row in rows}
            assert by_id[read].revoked_at is None
            assert by_id[read].authorized_org_ids is None
            assert by_id[write].revoked_at is not None
            assert (
                await db.scalar(text("SELECT name FROM users WHERE id=:id"), {"id": user})
                == "Preserved"
            )
            bound = uuid4()
            await db.execute(
                text(
                    "INSERT INTO management_sessions (id,identity_id,client_id,scope,name,"
                    "authenticated_at,created_at,last_active_at,expires_at,absolute_expires_at,"
                    "authorized_org_ids) SELECT :id,identity_id,client_id,scope,name,"
                    "authenticated_at,created_at,last_active_at,expires_at,absolute_expires_at,"
                    "CAST(:orgs AS json) FROM management_sessions WHERE id=:source"
                ),
                {"id": bound, "source": read, "orgs": '["' + str(uuid4()) + '"]'},
            )
            await db.run_sync(migrate, "114i_cli_settings", True)
            # A schema downgrade must never resurrect a revoked grant.
            assert await db.scalar(
                text("SELECT revoked_at FROM management_sessions WHERE id=:id"), {"id": write}
            )
            assert await db.scalar(
                text("SELECT revoked_at FROM management_sessions WHERE id=:id"), {"id": bound}
            )
            assert (
                await db.scalar(
                    text("SELECT revoked_at FROM management_sessions WHERE id=:id"), {"id": read}
                )
                is None
            )
            assert await db.scalar(text("SELECT count(*) FROM management_sessions")) == 3
    finally:
        await engine.dispose()
        async with owner.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
