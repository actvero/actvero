"""No old device, secret digest or expiry changes during policy upgrade."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_device_policy_upgrade_preserves_live_expired_revoked_and_tokens():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_device_policy_" + uuid4().hex
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

            await conn.run_sync(upgrade, "103x_web_session_policy")
            uid, identity = uuid4(), uuid4()
            await conn.execute(
                text("INSERT INTO users (id,name) VALUES (:id,'preserved')"), {"id": uid}
            )
            await conn.execute(
                text(
                    "INSERT INTO login_identities (id,user_id,issuer,subject,email_verified) "
                    "VALUES (:id,:uid,'https://identity.test','kept',true)"
                ),
                {"id": identity, "uid": uid},
            )
            for age, revoked in ((-1, False), (1, False), (1, True)):
                sid = uuid4()
                await conn.execute(
                    text(
                        "INSERT INTO device_sessions (id,identity_id,client_id,scope,"
                        "name,os,app_version,"
                        "authenticated_at,created_at,last_active_at,expires_at,"
                        "idle_expires_at,revoked_at) "
                        "VALUES (:id,:identity,'actvero-desktop','desktop:self','kept','macOS','1',"
                        "now(),now(),now(),now()+:age*interval '1 hour',"
                        "now()+:age*interval '1 hour',"
                        "CASE WHEN :revoked THEN now() ELSE NULL END)"
                    ),
                    {"id": sid, "identity": identity, "age": age, "revoked": revoked},
                )
                await conn.execute(
                    text(
                        "INSERT INTO device_tokens (token_hash,session_id,kind,"
                        "expires_at,response) "
                        "VALUES (:hash,:id,'refresh',now()+:age*interval '1 hour','sealed-kept')"
                    ),
                    {"hash": str(uuid4()), "id": sid, "age": age},
                )
            before = (
                (await conn.execute(text("SELECT to_jsonb(s) FROM device_sessions s ORDER BY id")))
                .scalars()
                .all()
            )
            tokens = (
                (
                    await conn.execute(
                        text("SELECT to_jsonb(s) FROM device_tokens s ORDER BY token_hash")
                    )
                )
                .scalars()
                .all()
            )
            await conn.run_sync(upgrade, "104y_device_session_policy")
            after = (
                (await conn.execute(text("SELECT to_jsonb(s) FROM device_sessions s ORDER BY id")))
                .scalars()
                .all()
            )
            current_tokens = (
                (
                    await conn.execute(
                        text("SELECT to_jsonb(s) FROM device_tokens s ORDER BY token_hash")
                    )
                )
                .scalars()
                .all()
            )
            for original, current in zip(before, after, strict=True):
                assert current.pop("policy_mode") == "strict"
                assert current.pop("absolute_expires_at") == original["expires_at"]
                assert current.pop("tenant_id") is None
                assert current == original
            for original, current in zip(tokens, current_tokens, strict=True):
                assert current.pop("acknowledged_at") is None
                assert current == original
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
