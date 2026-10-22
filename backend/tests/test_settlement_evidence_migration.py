"""97r preserves historical money and quota facts without inventing request evidence."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.asyncio
async def test_96q_settlements_upgrade_twice_and_refuse_downgrade(monkeypatch):
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    monkeypatch.setenv("ACTVERO_DATABASE_URL", url)
    schema = "test_settlement_97r_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head is not None
    async with owner.begin() as connection:
        await connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:

            def upgrade(sync, revision):
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, revision)

            def downgrade(sync, revision):
                cfg.attributes["connection"] = sync
                command.downgrade(cfg, revision)

            await connection.run_sync(upgrade, "96q_route_protection")

            def old_tables(sync):
                metadata = sa.MetaData()
                names = (
                    "tenants",
                    "users",
                    "memberships",
                    "model_channels",
                    "llm_models",
                    "llm_calls",
                    "llm_point_conversions",
                    "llm_settlements",
                    "llm_quota_clocks",
                )
                return {name: sa.Table(name, metadata, autoload_with=sync) for name in names}

            old = await connection.run_sync(old_tables)
            assert "request_fingerprint" not in old["llm_settlements"].c
            assert "evidence" not in old["llm_settlements"].c
            tenant, user, member, channel, model, conversion = (uuid4() for _ in range(6))
            stamp = datetime(2026, 9, 25, 1, 2, 3, tzinfo=UTC)
            await connection.execute(
                old["tenants"]
                .insert()
                .values(id=tenant, name="历史组织", active=True, created_at=stamp)
            )
            await connection.execute(
                old["users"].insert().values(id=user, name="历史成员", created_at=stamp)
            )
            await connection.execute(
                old["memberships"]
                .insert()
                .values(
                    id=member,
                    tenant_id=tenant,
                    user_id=user,
                    role="member",
                    status="active",
                    source="manual",
                    version=3,
                    joined_at=stamp,
                )
            )
            await connection.execute(
                old["model_channels"]
                .insert()
                .values(
                    id=channel,
                    tenant_id=tenant,
                    provider="openai-compatible",
                    name="历史渠道",
                    description="",
                    icon="",
                    base_url="https://example.test/v1",
                    connection={
                        "address_mode": "legacy_api_base",
                        "legacy_base_url": "https://example.test/v1",
                        "resolver_version": 1,
                    },
                    manual_enabled=True,
                    automatic_protection={"enabled": True},
                    routing_version=4,
                    auth_mode="none",
                    sealed_key=None,
                    timeout_seconds=20,
                    declared_apis=["chat_completions"],
                    archived=False,
                    version=4,
                    models=[{"id": "old-chat"}],
                    checks=[],
                    snapshot=["old-chat"],
                    created_at=stamp,
                )
            )
            await connection.execute(
                old["llm_models"]
                .insert()
                .values(
                    id=model,
                    tenant_id=tenant,
                    slug="old-chat",
                    name="历史模型",
                    configuration={"operations": [], "marker": "keep"},
                    archived=False,
                    version=9,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
            await connection.execute(
                old["llm_point_conversions"]
                .insert()
                .values(
                    id=conversion,
                    tenant_id=tenant,
                    currency="USD",
                    points_per_currency=Decimal("123.456789012345"),
                    version=7,
                    created_at=stamp,
                )
            )
            await connection.execute(
                old["llm_quota_clocks"]
                .insert()
                .values(
                    member_id=member,
                    tenant_id=tenant,
                    windows={"5": {"start": stamp.isoformat()}, "marker": "do-not-reset"},
                )
            )
            cases = (
                ("reserved", None, 1, Decimal("0.28")),
                ("review", None, 2, Decimal("0.56")),
                ("settled", Decimal("0.0244"), 5, Decimal("0.84")),
                ("released", Decimal("0"), 7, Decimal("0.07")),
            )
            for index, (status, amount, version, reserved_amount) in enumerate(cases):
                call_id = uuid4()
                created_at = stamp + timedelta(minutes=index)
                await connection.execute(
                    old["llm_calls"]
                    .insert()
                    .values(
                        id=call_id,
                        tenant_id=tenant,
                        model_id=model,
                        channel_id=channel,
                        actor_id=user,
                        source="desktop",
                        kind="chat",
                        status="succeeded" if status == "settled" else "unknown",
                        attempts=[{"number": 1, "status": status, "legacy": "keep"}],
                        usage={"legacy": status},
                        prices={"budget": {"marker": status}},
                        estimates={"legacy": status},
                        created_at=created_at,
                    )
                )
                await connection.execute(
                    old["llm_settlements"]
                    .insert()
                    .values(
                        id=call_id,
                        tenant_id=tenant,
                        member_id=member,
                        idempotency_key=f"old-key-{status}",
                        currency="USD",
                        conversion_id=conversion,
                        ratio=Decimal("123.456789012345"),
                        reserved_amount=reserved_amount,
                        amount=amount,
                        price={
                            "currency": "USD",
                            "metric": "tokens",
                            "unit": 1000000,
                            "input": "1.25",
                            "output": "2.5",
                            "marker": status,
                        },
                        policy_snapshot={
                            "policy": {"id": "historical", "version": 6},
                            "windows": [{"reserved": str(reserved_amount)}],
                            "marker": status,
                        },
                        usage={"source": "unknown", "marker": status},
                        status=status,
                        version=version,
                        reason=f"historical {status}",
                        created_at=created_at,
                        settled_at=created_at + timedelta(seconds=3)
                        if amount is not None
                        else None,
                    )
                )

            async def snapshots():
                result = {}
                for table in (
                    "llm_settlements",
                    "llm_calls",
                    "llm_point_conversions",
                    "llm_quota_clocks",
                ):
                    result[table] = {
                        row["id"] if "id" in row else row["member_id"]: row
                        for row in (
                            await connection.execute(sa.text(f"SELECT to_jsonb(t) FROM {table} t"))
                        ).scalars()
                    }
                return result

            before = await snapshots()
            assert len(before["llm_settlements"]) == 4
            await connection.run_sync(upgrade, "head")
            assert await connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
                head
            )
            after = await snapshots()
            for key, saved in after["llm_settlements"].items():
                assert saved["request_fingerprint"] is None
                assert saved["evidence"] == {}
                assert {
                    field: value
                    for field, value in saved.items()
                    if field not in {"request_fingerprint", "evidence"}
                } == before["llm_settlements"][key]
            for table in ("llm_calls", "llm_point_conversions", "llm_quota_clocks"):
                assert after[table] == before[table]

            # A second head upgrade is a no-op, including the nullable legacy identity.
            await connection.run_sync(upgrade, "head")
            repeated = await snapshots()
            assert repeated == after
            # Roll back the failed downgrade command, including newer reversible
            # revisions, while preserving this fixture's outer transaction.
            with pytest.raises(RuntimeError, match="restore the pre-upgrade backup"):
                async with connection.begin_nested():
                    await connection.run_sync(downgrade, "96q_route_protection")
            assert await connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
                head
            )
            assert await snapshots() == after
    finally:
        await engine.dispose()
        async with owner.begin() as connection:
            await connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
