"""Atomic preview/commit behavior against isolated PostgreSQL; no vendor calls."""

import asyncio
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel

from app.modules.llm.models import CatalogModel, ModelChannel, ModelImportReceipt

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/model-imports"


async def source(admin):
    return await create_channel(
        admin,
        models=[{"id": value} for value in ["text-embedding-3-small", "unknown", "other"]],
        provider="openai",
        declared_apis=["chat_completions", "embeddings"],
    )


def plan(channel, items=None):
    return {
        "channel_id": channel["id"],
        "channel_version": channel["version"],
        "items": items or [{"upstream_id": "text-embedding-3-small"}, {"upstream_id": "unknown"}],
    }


async def preview(admin, body):
    result = await admin.api.post(BASE + "/preview", json=body)
    assert result.status_code == 200, result.text
    return result.json()


async def submission(admin, body):
    result = await preview(admin, body)
    assert result["can_commit"], result
    return {**body, "request_id": str(uuid4()), "revision": result["revision"]}


async def count(env, table):
    async with env.sessions() as db:
        return await db.scalar(select(func.count()).select_from(table))


async def test_preview_readonly_closed_creation_unknown_source_and_receipt(env):
    admin = await env.client()
    channel = await source(admin)
    body = plan(channel)
    result = await preview(admin, body)
    assert result["create_count"] == 2 and result["binding_count"] == 1
    assert result["items"][0]["kinds"] == ["embedding"]
    assert result["items"][1]["kinds"] == []
    assert await count(env, CatalogModel) == await count(env, ModelImportReceipt) == 0
    command = {**body, "request_id": str(uuid4()), "revision": result["revision"]}
    response = await admin.api.post(BASE + "/commit", json=command)
    assert response.status_code == 200, response.text
    result = response.json()
    for item in result["items"]:
        model = (await admin.api.get("/api/v1/llm/models/" + item["model_id"])).json()
        assert (
            model["access"]["enabled"] is False and model["access"]["audience"] == "administrators"
        )
        assert model["reference"]["channel_id"] == channel["id"]
        assert model["budget_price"] is None
        assert len(model["operations"]) == (1 if item["upstream_id"].startswith("text") else 0)
        for op in model["operations"]:
            assert op["enabled"] is False
            assert op["bindings"][0]["enabled"] is False
            assert op["bindings"][0]["price"] is None
    repeated = await admin.api.post(BASE + "/commit", json=command)
    assert repeated.status_code == 200 and repeated.json() == result
    status = (await admin.api.get(BASE + "/" + command["request_id"])).json()
    assert status == {"committed": True, "result": result}
    changed = deepcopy(command)
    changed["items"][0]["slug"] = "different"
    assert (await admin.api.post(BASE + "/commit", json=changed)).status_code == 409
    assert await count(env, CatalogModel) == 2 and await count(env, ModelImportReceipt) == 1


async def test_link_preserves_configuration_dedupes_and_versions_target_once(env):
    admin = await env.client()
    member = await env.client(role="member")
    channel = await source(admin)
    target = (
        await admin.api.post(
            "/api/v1/llm/models",
            json={
                "slug": "existing",
                "name": "Existing",
                "access": {"audience": "selected", "member_ids": [str(member.member.id)]},
                "operations": [
                    {
                        "kind": "embedding",
                        "budget_price": {"currency": "CNY", "input": "0.987654321"},
                        "retrieval": {"dimensions": 64, "embedding_space": "kept-space"},
                        "routing": {"cooldown_seconds": 47, "max_attempts": 2},
                        "bindings": [
                            {
                                "channel_id": channel["id"],
                                "upstream_id": "text-embedding-3-small",
                                "enabled": True,
                                "priority": 4,
                                "weight": 29,
                                "price": {"currency": "USD", "input": "0.123456789"},
                            }
                        ],
                    }
                ],
            },
        )
    ).json()
    before = deepcopy(target)
    body = plan(
        channel,
        [
            {
                "upstream_id": upstream,
                "action": "link",
                "target_id": target["id"],
                "kinds": ["embedding"],
            }
            for upstream in ["unknown", "other"]
        ],
    )
    command = await submission(admin, body)
    result = await admin.api.post(BASE + "/commit", json=command)
    assert result.status_code == 200, result.text
    after = (await admin.api.get("/api/v1/llm/models/" + target["id"])).json()
    assert after["version"] == before["version"] + 1
    assert len(after["operations"][0]["bindings"]) == 3
    assert after["operations"][0]["bindings"][0] == before["operations"][0]["bindings"][0]
    assert all(
        not b["enabled"] and b["price"] is None for b in after["operations"][0]["bindings"][1:]
    )
    assert after["access"] == before["access"]
    op_before, op_after = before["operations"][0], after["operations"][0]
    assert {k: v for k, v in op_after.items() if k != "bindings"} == {
        k: v for k, v in op_before.items() if k != "bindings"
    }
    repeated = await preview(admin, body)
    assert not repeated["can_commit"] and all(r["status"] == "unchanged" for r in repeated["items"])
    body["items"].append({"upstream_id": "text-embedding-3-small", "slug": "new"})
    command = await submission(admin, body)
    assert (await admin.api.post(BASE + "/commit", json=command)).status_code == 200
    unchanged = (await admin.api.get("/api/v1/llm/models/" + target["id"])).json()
    assert unchanged["version"] == after["version"]


@pytest.mark.parametrize("change", ["channel", "target", "name"])
async def test_stale_preview_never_partially_writes(env, change):
    admin = await env.client()
    channel = await source(admin)
    body = plan(channel)
    target = (
        await admin.api.post(
            "/api/v1/llm/models",
            json={
                "slug": "target",
                "name": "Target",
                "operations": [{"kind": "chat"}],
            },
        )
    ).json()
    if change == "target":
        body["items"][1].update(action="link", target_id=target["id"], kinds=["chat"])
    command = await submission(admin, body)
    if change == "name":
        await admin.api.post(
            "/api/v1/llm/models", json={"slug": "unknown", "name": "Collision", "operations": []}
        )
    else:
        async with env.sessions() as db:
            row = await db.get(
                ModelChannel if change == "channel" else CatalogModel,
                UUID(channel["id"] if change == "channel" else target["id"]),
            )
            row.version += 1
            await db.commit()
    previous_count = await count(env, CatalogModel)
    assert (await admin.api.post(BASE + "/commit", json=command)).status_code == 409
    assert await count(env, CatalogModel) == previous_count
    assert await count(env, ModelImportReceipt) == 0


async def test_preview_errors_skip_limits_permissions_and_concurrent_commit(env):
    admin, member = await env.client(), await env.client(role="member")
    channel = await source(admin)
    body = plan(
        channel,
        [
            {"upstream_id": "unknown", "slug": "duplicate"},
            {"upstream_id": "other", "slug": "duplicate"},
        ],
    )
    result = await preview(admin, body)
    assert not result["can_commit"] and all(r["errors"] for r in result["items"])
    body["items"][1]["action"] = "skip"
    assert (await preview(admin, body))["can_commit"]
    body["items"][0]["kinds"] = ["rerank"]
    assert not (await preview(admin, body))["can_commit"]
    body["items"][0]["kinds"] = []
    command = await submission(admin, body)
    assert (await member.api.post(BASE + "/preview", json=body)).status_code == 403
    assert (await member.api.post(BASE + "/commit", json=command)).status_code == 403
    assert (await member.api.get(BASE + "/" + command["request_id"])).status_code == 403
    for items in [body["items"] * 2, [{"upstream_id": f"m{i}"} for i in range(51)]]:
        assert (
            await admin.api.post(BASE + "/preview", json={**body, "items": items})
        ).status_code == 422
    responses = await asyncio.gather(
        *[admin.api.post(BASE + "/commit", json=command) for _ in range(2)]
    )
    assert all(r.status_code == 200 for r in responses)
    assert responses[0].json() == responses[1].json()
    assert await count(env, CatalogModel) == 1 and await count(env, ModelImportReceipt) == 1
    other_admin = await env.client()
    assert (await other_admin.api.get(BASE + "/" + command["request_id"])).json()[
        "committed"
    ] is False


async def test_failed_second_write_rolls_back_models_audit_and_receipt(env, monkeypatch):
    from fastapi import HTTPException

    from app.modules.audit.models import AuditEvent
    from app.modules.llm import import_router

    admin = await env.client()
    channel = await source(admin)
    command = await submission(admin, plan(channel))
    audit_before = await count(env, AuditEvent)
    original = import_router.configure
    calls = 0

    async def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HTTPException(422, "测试隔离：第二条保存失败")
        return await original(*args)

    monkeypatch.setattr(import_router, "configure", fail_second)
    assert (await admin.api.post(BASE + "/commit", json=command)).status_code == 422
    assert calls == 2
    assert await count(env, CatalogModel) == await count(env, ModelImportReceipt) == 0
    assert await count(env, AuditEvent) == audit_before


async def test_authorization_source_validity_and_preview_tampering(env):
    admin, outsider = await env.client(), await env.client(joined=False)
    channel = await source(admin)
    body = plan(channel)
    command = await submission(admin, body)
    for route, data in [("/preview", body), ("/commit", command)]:
        assert (await outsider.api.post(BASE + route, json=data)).status_code == 403
        for headers in [{"origin": "https://invalid.example"}, {"x-csrf-token": "wrong"}]:
            assert (
                await admin.api.post(BASE + route, json=data, headers=headers)
            ).status_code == 403
    assert (
        await admin.api.post(BASE + "/preview", json={**body, "channel_id": str(uuid4())})
    ).status_code == 404
    tampered = deepcopy(command)
    tampered["items"][0]["slug"] = "unpreviewed"
    assert (await admin.api.post(BASE + "/commit", json=tampered)).status_code == 409
    assert not (await preview(admin, plan(channel, [{"upstream_id": "removed"}])))["can_commit"]
    async with env.sessions() as db:
        source_row = await db.get(ModelChannel, UUID(channel["id"]))
        source_row.archived = True
        await db.commit()
    assert (await admin.api.post(BASE + "/commit", json=command)).status_code == 409
    assert await count(env, CatalogModel) == await count(env, ModelImportReceipt) == 0
    admin.api.cookies.clear()
    assert (await admin.api.get(BASE + "/" + command["request_id"])).status_code == 401


async def test_receipt_migration_and_non_destructive_downgrade(env):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    spec = importlib.util.spec_from_file_location(
        "receipt_migration", Path("migrations/versions/91l_model_import_receipts.py")
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = env.app.state.database.engine

    def migrate(connection, callback):
        with Operations.context(MigrationContext.configure(connection)):
            callback()

    # This table belongs only to this test's random schema.
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE llm_model_import_receipts"))
        await conn.run_sync(lambda c: migrate(c, migration.upgrade))
    admin = await env.client()
    channel = await source(admin)
    command = await submission(admin, plan(channel))
    assert (await admin.api.post(BASE + "/commit", json=command)).status_code == 200
    async with engine.begin() as conn:
        with pytest.raises(RuntimeError, match="不能无损回退"):
            await conn.run_sync(lambda c: migrate(c, migration.downgrade))
    assert await count(env, ModelImportReceipt) == 1
    assert await count(env, CatalogModel) == 2
