"""Diagnostic admission adds a nullable identity without rewriting historical calls."""

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.modules.llm.models import CatalogModel, ModelCall
from app.modules.tenants.models import Tenant
from app.modules.users.models import User


def test_diagnostic_downgrade_refuses_data_loss():
    spec = importlib.util.spec_from_file_location(
        "diagnostic_migration", Path("migrations/versions/95p_diagnostic_calls.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(RuntimeError, match="诊断记录不能自动删除"):
        module.downgrade()


@pytest.mark.asyncio
async def test_diagnostic_upgrade_preserves_calls_and_requires_explicit_identity(monkeypatch):
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    monkeypatch.setenv("ACTVERO_DATABASE_URL", url)
    schema = "test_diagnostic_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    async with owner.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as connection:

            def upgrade(sync, target):
                cfg.attributes["connection"] = sync
                command.upgrade(cfg, target)

            await connection.run_sync(upgrade, "94o_channel_management")
            tenant, user, channel, model, call = (uuid4() for _ in range(5))
            await connection.execute(Tenant.__table__.insert().values(id=tenant, name="保留组织"))
            await connection.execute(User.__table__.insert().values(id=user, name="保留成员"))
            # Historical gateway 94o has no legacy channel-routing branch column.
            await connection.execute(
                text(
                    "INSERT INTO model_channels "
                    "(id, tenant_id, provider, name, description, icon, base_url, auth_mode, "
                    "timeout_seconds, declared_apis, archived, version, models, checks, snapshot, "
                    "created_at, connection, manual_enabled, automatic_protection) "
                    "VALUES (:id, :tenant, 'openai-compatible', '原渠道', '', '', "
                    "'https://example.com/v1', 'none', 20, '[]', false, 1, '[]', '[]', '[]', "
                    "now(), '{}', true, CAST(:protection AS jsonb))"
                ),
                {"id": channel, "tenant": tenant, "protection": '{"enabled":true}'},
            )
            await connection.execute(
                CatalogModel.__table__.insert().values(
                    id=model,
                    tenant_id=tenant,
                    slug="old",
                    name="原模型",
                    configuration={},
                )
            )
            values = {
                "tenant_id": tenant,
                "channel_id": channel,
                "actor_id": user,
                "kind": "chat",
            }
            # Original records contain no evidence of actual dispatch/termination.
            await connection.execute(
                ModelCall.__table__.insert().values(
                    **values,
                    id=call,
                    model_id=model,
                    source="desktop",
                    status="unknown",
                    attempts=[{"number": 1, "status": "unknown", "usage": {"source": "unknown"}}],
                )
            )
            before = await connection.scalar(text("SELECT to_jsonb(c) FROM llm_calls c"))
            await connection.run_sync(upgrade, "head")
            assert await connection.scalar(text("SELECT to_jsonb(c) FROM llm_calls c")) == before
            assert "sent" not in before["attempts"][0]

            await connection.execute(
                ModelCall.__table__.insert().values(
                    **values,
                    model_id=None,
                    source="channel_diagnostic",
                    status="pending",
                )
            )
            # Both directions are constrained; a regular call still requires a model.
            for source, model_id in [("desktop", None), ("channel_diagnostic", model)]:
                with pytest.raises(IntegrityError, match="ck_llm_call_model_source"):
                    async with connection.begin_nested():
                        await connection.execute(
                            ModelCall.__table__.insert().values(
                                **values,
                                model_id=model_id,
                                source=source,
                                status="pending",
                            )
                        )
            assert await connection.scalar(text("SELECT count(*) FROM llm_calls")) == 2
    finally:
        await engine.dispose()
        async with owner.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
