"""Upgrade preserves Web credentials, exact expiry, and frozen old strict policy."""

import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_upgrade_does_not_extend_expired_or_live_web_sessions():
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    schema = "test_web_policy_" + uuid4().hex
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

            await conn.run_sync(upgrade, "102w_freeze_legacy_routes")
            uid, identity = uuid4(), uuid4()
            await conn.execute(
                text("INSERT INTO users (id, name) VALUES (:id, 'preserved')"), {"id": uid}
            )
            await conn.execute(
                text(
                    "INSERT INTO login_identities (id, user_id, issuer, subject, email_verified) "
                    "VALUES (:id, :uid, 'https://identity.test', 'kept', true)"
                ),
                {"id": identity, "uid": uid},
            )
            for age in (-1, 1):
                await conn.execute(
                    text(
                        "INSERT INTO web_sessions (id, token_hash, csrf, identity_id, tokens, "
                        "authenticated_at, expires_at) VALUES (:id, :hash, 'csrf-kept', "
                        ":identity, 'encrypted-kept', now(), now() + :age * interval '1 hour')"
                    ),
                    {"id": uuid4(), "hash": str(uuid4()), "identity": identity, "age": age},
                )
            before = (
                (await conn.execute(text("SELECT to_jsonb(s) FROM web_sessions s ORDER BY id")))
                .scalars()
                .all()
            )
            await conn.run_sync(upgrade, "103x_web_session_policy")
            after = (
                (await conn.execute(text("SELECT to_jsonb(s) FROM web_sessions s ORDER BY id")))
                .scalars()
                .all()
            )
            for original, current in zip(before, after, strict=True):
                assert current.pop("policy_mode") == "strict"
                assert current.pop("absolute_expires_at") == original["expires_at"]
                assert current.pop("renewed_at") is None
                assert current == original
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
