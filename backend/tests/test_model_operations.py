"""Multiple operations share identity, never routes, prices or test certificates."""

from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Request
from llm_billing_helpers import billing
from sqlalchemy import select
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel
from test_llm_retrieval import upstream
from test_llm_routing import update
from test_mcp import listening

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import ModelCall, UsageSettlement

pytestmark = pytest.mark.asyncio
env = identity_env
BASE = "/api/v1/llm/models/"
GATEWAY = "/api/llm/v1"


def operation(kind, channel, *, enabled=True):
    return {
        "kind": kind,
        "enabled": enabled,
        "channel_id": channel["id"],
        "upstream_id": "upstream",
        "retrieval": {"dimensions": 3, "embedding_space": "space-v1", "max_search_units": 4},
        "context_window": 1000,
        "max_output": 20,
        "routing": {"model_revision": "space-v1"},
        "bindings": [
            {
                "channel_id": channel["id"],
                "upstream_id": "upstream",
                "enabled": True,
                "compatibility_key": "space-v1",
            }
        ],
        "budget_price": {
            "currency": "USD",
            "input": "2",
            **(
                {"output": "8"}
                if kind == "chat"
                else {"metric": "search_units"}
                if kind == "rerank"
                else {}
            ),
        },
    }


async def create(admin, channel, **extra):
    result = await admin.api.post(
        BASE.rstrip("/"),
        json={
            "name": "多操作",
            "slug": "multi",
            "access": {"enabled": True, "audience": "organization"},
            "operations": [operation(k, channel) for k in ("chat", "embedding", "rerank")],
            **extra,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


async def test_shared_model_dispatch_prices_permissions_and_space_lock(env, monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    app, calls = upstream()

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        data = await request.json()
        calls.append((dict(request.headers), data))
        return {
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }

    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        channel = await create_channel(
            admin,
            base_url=base + "/v1",
            models=[{"id": "upstream"}],
            declared_apis=["chat_completions", "embeddings", "rerank"],
        )
        model = await create(admin, channel)
        key, _ = await create_key(member)
        directory = await api.get(GATEWAY + "/models", headers=headers(key))
        assert directory.status_code == 200, directory.text
        assert [o["kind"] for o in directory.json()["data"][0]["operations"]] == [
            "chat",
            "embedding",
            "rerank",
        ]
        assert "channel_id" not in directory.text and "budget_price" not in directory.text
        for endpoint, payload in [
            ("chat/completions", {"messages": [{"role": "user", "content": "hello"}]}),
            ("embeddings", {"input": "text"}),
            ("rerank", {"query": "q", "documents": ["one", "two"]}),
        ]:
            result = await api.post(
                GATEWAY + "/" + endpoint, json={"model": "multi", **payload}, headers=headers(key)
            )
            assert result.status_code == 200, result.text
        assert len(calls) == 3 and all(body["model"] == "upstream" for _, body in calls)
        async with env.sessions() as db:
            logs = list(await db.scalars(select(ModelCall).order_by(ModelCall.created_at)))
            assert [log.kind for log in logs] == ["chat", "embedding", "rerank"]
            assert [log.estimates["budget"]["amount"] for log in logs] == [
                "0.000036",
                "0.00002",
                "0.000004",
            ]
            settlements = list(await db.scalars(select(UsageSettlement)))
            assert len(settlements) == 3 and all(s.status == "settled" for s in settlements)
        # Embedding space is protected even when chat is the primary projection.
        changed = deepcopy(model["operations"])
        changed[1]["retrieval"]["dimensions"] = 5
        result = await admin.api.put(
            BASE + model["id"],
            json={
                "name": model["name"],
                "slug": model["slug"],
                "version": model["version"],
                "access": model["access"],
                "operations": changed,
            },
        )
        assert result.status_code == 409, result.text
        changed = deepcopy(model["operations"])
        changed[1]["enabled"] = False
        model = await update(admin, model, operations=changed)
        result = await api.post(
            GATEWAY + "/embeddings", json={"model": "multi", "input": "text"}, headers=headers(key)
        )
        assert result.status_code == 404 and len(calls) == 3
        directory = (await api.get(GATEWAY + "/models", headers=headers(key))).json()
        assert [o["kind"] for o in directory["data"][0]["operations"]] == ["chat", "rerank"]
        # Legacy clients cannot erase the other operations by writing only root fields.
        result = await admin.api.put(
            BASE + model["id"],
            json={"slug": "multi", "name": "old client", "version": model["version"]},
        )
        assert result.status_code == 409
        model = await update(admin, model, access={**model["access"], "audience": "administrators"})
        assert not (await api.get(GATEWAY + "/models", headers=headers(key))).json()["data"]


async def test_operation_defaults_filter_and_test_certificates(env):
    admin = await env.client()
    app, calls = upstream()
    async with listening(app) as base:
        env.provider.settings.llm_allowed_private_origins = [base]
        channel = await create_channel(
            admin,
            base_url=base + "/v1",
            models=[{"id": "upstream"}],
            declared_apis=["embeddings", "rerank"],
        )
        model = await create(
            admin,
            channel,
            access={"enabled": False},
            operations=[operation(k, channel) for k in ("embedding", "rerank")],
        )
        url = BASE + model["id"]
        result = await admin.api.post(
            url + "/test/embeddings",
            params={"channel_id": channel["id"], "upstream_id": "upstream"},
            json={"model": "multi", "input": "test"},
        )
        assert result.status_code == 200, result.text
        states = (await admin.api.get(url + "/routes")).json()
        assert [(s["operation"], s["state"]) for s in states] == [
            ("embedding", "ready"),
            ("rerank", "ready"),
        ]
        assert (await admin.api.get(BASE.rstrip("/"), params={"kind": "rerank"})).json()[
            "total"
        ] == 1
        assert (await admin.api.get(BASE.rstrip("/"), params={"kind": "chat"})).json()["total"] == 0
        changed = deepcopy(model["operations"])
        changed.append(
            {"kind": "chat", "bindings": [{"channel_id": channel["id"], "upstream_id": "upstream"}]}
        )
        model = await update(admin, model, operations=changed)
        assert model["operations"][2]["enabled"] is False
        assert model["operations"][2]["bindings"][0]["enabled"] is False
        # A stale version and a duplicate operation cannot replace the saved configuration.
        result = await admin.api.put(
            url,
            json={
                "name": "duplicate",
                "slug": "multi",
                "version": model["version"],
                "operations": [changed[0], changed[0]],
            },
        )
        assert result.status_code == 422
        result = await admin.api.put(
            url,
            json={
                "name": "stale",
                "slug": "multi",
                "version": model["version"] - 1,
                "operations": changed,
            },
        )
        assert result.status_code == 409
        assert len(calls) == 1


async def test_unknown_operation_draft_and_legacy_projection(env):
    admin = await env.client()
    draft = await admin.api.post(
        BASE.rstrip("/"), json={"name": "draft", "slug": "draft", "operations": []}
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["operations"] == []
    config = CatalogInput.model_validate(
        {
            "name": "old",
            "slug": "old",
            "kind": "rerank",
            "bindings": [{"channel_id": str(UUID(int=1)), "upstream_id": "one"}],
        }
    )
    projected = config.for_operation("rerank")
    assert projected.kind == "rerank" and projected.bindings[0].enabled
    assert config.for_operation("chat") is None
    for operations in [[], [{"kind": "chat"}], [{"kind": "image_generation"}]]:
        result = await admin.api.post(
            BASE.rstrip("/"),
            json={
                "name": "bad",
                "slug": "bad",
                "access": {"enabled": True},
                "operations": operations,
            },
        )
        assert result.status_code == 422


async def test_migration_preserves_legacy_configuration_and_route_evidence(env):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from test_llm_catalog import create as legacy_create

    from app.modules.auth.service import now
    from app.modules.llm import routing
    from app.modules.llm.models import CatalogModel, RouteHealth

    admin = await env.client()
    channel = await create_channel(admin, models=[{"id": "upstream"}])
    model = await legacy_create(
        admin,
        slug="old-one",
        bindings=[
            {
                "channel_id": channel["id"],
                "upstream_id": "upstream",
                "enabled": True,
            }
        ],
        budget_price={"currency": "USD", "input": "1", "output": "2"},
    )
    model_id, channel_id = UUID(model["id"]), UUID(channel["id"])
    previous_key = routing.hash_value([admin.tenant.id, model_id, channel_id, "upstream"])
    async with env.sessions() as db:
        db.add(
            RouteHealth(
                id=previous_key,
                tenant_id=admin.tenant.id,
                fingerprint="original",
                tested_at=now(),
                failures=2,
            )
        )
        await db.commit()
        original = deepcopy((await db.get(CatalogModel, model_id)).configuration)
        tested = (await db.get(RouteHealth, previous_key)).tested_at

        def migrate(connection):
            spec = importlib.util.spec_from_file_location(
                "operation_migration", Path("migrations/versions/90k_model_operations.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.op = Operations(MigrationContext.configure(connection))
            module.upgrade()
            module.upgrade()

        await (await db.connection()).run_sync(migrate)
        await db.commit()
        row = await db.get(CatalogModel, model_id, populate_existing=True)
        assert {k: v for k, v in row.configuration.items() if k != "operations"} == {
            k: v for k, v in original.items() if k != "operations"
        }
        operation_config = CatalogInput.model_validate(row.configuration).for_operation("chat")
        assert operation_config.budget_price.input == 1
        health = await db.get(
            RouteHealth,
            routing.health_key(admin.tenant.id, model_id, "chat", operation_config.bindings[0]),
        )
        assert health.tested_at == tested and health.failures == 2
        assert health.fingerprint == "original"
        assert operation_config.access.enabled is False
