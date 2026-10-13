"""Channel gates and read-only health projection on isolated PostgreSQL."""

from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_identity_access import env as identity_env

from app.modules.auth.service import now
from app.modules.llm import routing
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.channel_health import project_channel_health
from app.modules.llm.model_endpoints import project_endpoints
from app.modules.llm.models import CatalogModel, ModelChannel, RouteHealth

env = identity_env
pytestmark = pytest.mark.asyncio


def channel(tenant_id, *, name="one"):
    return ModelChannel(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        provider="openai",
        base_url="https://example.test/v1",
        auth_mode="none",
        sealed_key=None,
        declared_apis=["embeddings"],
        models=[{"id": "upstream"}],
        archived=False,
        manual_enabled=True,
        automatic_protection={"enabled": True},
        timeout_seconds=20,
        version=1,
        routing_version=1,
    )


def catalog(tenant_id, channels, *, mode="auto"):
    config = CatalogInput.model_validate(
        {
            "name": "向量模型",
            "slug": "channel-health",
            "kind": "embedding",
            "retrieval": {
                "dimensions": 3,
                "embedding_space": "same-space",
            },
            "routing": {
                "mode": mode,
                "failure_threshold": 2,
                "cooldown_seconds": 30,
            },
            "access": {
                "enabled": True,
                "audience": "organization",
                "channel_id": str(channels[0].id),
                "upstream_id": "upstream",
            },
            "budget_price": {"currency": "USD", "input": "1"},
            "bindings": [
                {
                    "channel_id": str(item.id),
                    "upstream_id": "upstream",
                    "enabled": True,
                    "compatibility_key": "same-space",
                    "price": {"currency": "USD", "input": "1"},
                }
                for item in channels
            ],
        }
    )
    row = CatalogModel(
        id=uuid4(),
        tenant_id=tenant_id,
        name=config.name,
        slug=config.slug,
        configuration=config.model_dump(mode="json"),
        archived=False,
        version=1,
    )
    return row, config


async def test_manual_gate_specific_diagnostic_and_fingerprint(env):
    admin = await env.client()
    async with env.sessions() as db:
        item = channel(admin.tenant.id)
        row, config = catalog(admin.tenant.id, [item], mode="fixed")
        db.add_all([item, row])
        await db.commit()
        binding = config.bindings[0]
        original_fp = routing.fingerprint(config, binding, item)
        item.version = 2  # Cosmetic edit must not erase existing health.
        item.manual_enabled = False
        assert routing.fingerprint(config, binding, item) == original_fp
        assert not routing.available(config, binding, item)
        assert (
            await routing.state(
                db, admin.tenant.id, row.id, config, binding, item, require_test=False
            )
        )[0] == "manual_disabled"
        with pytest.raises(HTTPException):
            routing.configured_candidates(config, {item.id: item})
        assert routing.available(config, binding, item, ignore_manual_enabled=True)
        binding.enabled = False
        assert routing.available(
            config, binding, item, allow_disabled=True, ignore_manual_enabled=True
        )
        binding.enabled = True
        endpoint = await project_endpoints(db, admin.tenant.id, row, config, {item.id: item})
        embedding = next(value for value in endpoint.endpoints if value.operation == "embedding")
        assert not embedding.open and "manual_disabled" in embedding.reasons
        item.archived = True
        assert not routing.available(
            config, binding, item, allow_disabled=True, ignore_manual_enabled=True
        )
        item.archived = False
        item.manual_enabled = None  # Legacy, unflushed ORM object.
        item.routing_version = None
        item.version = 1
        assert routing.available(config, binding, item)
        assert routing.fingerprint(config, binding, item) == original_fp


async def test_channel_summary_is_read_only_and_ignores_manual_gate(env):
    admin = await env.client()
    async with env.sessions() as db:
        first = channel(admin.tenant.id)
        second = channel(admin.tenant.id, name="two")
        unused = channel(admin.tenant.id, name="unused")
        row, config = catalog(admin.tenant.id, [first, second])
        db.add_all([first, second, unused, row])
        await db.commit()
        first.manual_enabled = False
        first_health = RouteHealth(
            id=routing.health_key(admin.tenant.id, row.id, config.kind, config.bindings[0]),
            tenant_id=admin.tenant.id,
            fingerprint=routing.fingerprint(config, config.bindings[0], first),
            tested_at=now(),
            failures=0,
            blocked=False,
        )
        db.add(first_health)
        await db.commit()
        count_before = await db.scalar(select(func.count()).select_from(RouteHealth))
        summary = await project_channel_health(db, [first, second, unused])
        assert summary[first.id].state == "ready"
        assert summary[first.id].health_counts == {"ready": 1}
        assert summary[second.id].state == "ready"
        assert summary[unused.id].state == "no_routes"
        assert summary[first.id].as_of == summary[second.id].as_of
        assert await db.scalar(select(func.count()).select_from(RouteHealth)) == count_before
        assert not db.dirty and not db.new

        additional, _ = catalog(admin.tenant.id, [first])
        additional.slug = "second-reference"
        db.add(additional)
        await db.commit()
        summary = await project_channel_health(db, [first])
        assert summary[first.id].state == "ready"
        assert summary[first.id].health_counts == {"ready": 2}
        additional.archived = True
        first_health.cooldown_until = now() + timedelta(seconds=30)
        await db.commit()
        summary = await project_channel_health(db, [first, second])
        assert summary[first.id].state == "ready"
        first.archived = True
        await db.commit()
        summary = await project_channel_health(db, [first, second])
        assert summary[first.id].state == "not_applicable"
        assert summary[first.id].health_counts == {}


async def test_fixed_binding_health_uses_the_runtime_gate(env):
    admin = await env.client()
    async with env.sessions() as db:
        item = channel(admin.tenant.id)
        row, config = catalog(admin.tenant.id, [item], mode="fixed")
        db.add_all([item, row])
        await db.commit()
        # A fixed route does not require an earlier diagnostic certification.
        assert (
            await routing.state(
                db,
                admin.tenant.id,
                row.id,
                config,
                config.bindings[0],
                item,
                require_test=False,
            )
        )[0] == "ready"
        summary = await project_channel_health(db, [item])
        assert summary[item.id].state == "ready"
        assert summary[item.id].health_counts == {"ready": 1}
