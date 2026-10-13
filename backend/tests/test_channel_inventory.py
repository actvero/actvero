"""Inventory protection, scoped projections and diagnostic status on isolated PostgreSQL."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_llm_channels import create

from app.modules.audit.models import AuditEvent
from app.modules.auth.service import now
from app.modules.llm.models import CatalogModel, ModelChannel, RouteHealth

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/channels"
CATALOG = "/api/v1/llm/models"


async def linked(admin, channel, *, enabled=True):
    result = await admin.api.post(
        CATALOG,
        json={
            "name": "关联模型",
            "slug": "inventory-" + uuid4().hex,
            "operations": [
                {
                    "kind": "chat",
                    "enabled": False,
                    "bindings": [
                        {
                            "channel_id": channel["id"],
                            "upstream_id": "bound",
                            "enabled": enabled,
                        }
                    ],
                }
            ],
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


@pytest.mark.parametrize("method", ["DELETE", "PUT"])
async def test_active_binding_guard_protects_both_removal_paths_atomically(env, method):
    admin = await env.client()
    channel = await create(admin, manual_enabled=False, models=[{"id": "bound"}, {"id": "free"}])
    model = await linked(admin, channel)
    path = BASE + "/" + channel["id"]
    body = {"version": channel["version"], "models": [{"id": "bound"}, {"id": "free"}]}
    if method == "PUT":
        body.update(name="Should roll back", models=[])
    response = await admin.api.request(
        method, path + ("/models" if method == "DELETE" else ""), json=body
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["references"] == [
        {
            "model_id": model["id"],
            "model_name": model["name"],
            "operation": "chat",
            "binding_id": model["bindings"][0]["binding_id"],
        }
    ]
    assert "test-secret" not in response.text and "price" not in response.text
    after = (await admin.api.get(path)).json()
    assert after["version"] == channel["version"] and after["name"] == channel["name"]
    assert [m["id"] for m in after["models"]] == ["bound", "free"]
    assert not after["manual_enabled"]
    # An unrelated stock item can still be removed; model/operation are both off,
    # so the guard above proves their switches do not erase an enabled reference.
    free = await admin.api.request(
        "DELETE",
        path + "/models",
        json={
            "version": after["version"],
            "models": [{"id": "free"}],
        },
    )
    assert free.status_code == 200, free.text
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(RouteHealth)) == 0
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "llm.channel.models.remove")
            )
            == 1
        )


@pytest.mark.parametrize("archived_model", [False, True])
async def test_disabled_or_archived_references_are_preserved_after_stock_removal(
    env, archived_model
):
    admin = await env.client()
    channel = await create(admin, models=[{"id": "bound"}])
    model = await linked(admin, channel, enabled=archived_model)
    if archived_model:
        result = await admin.api.put(
            CATALOG + "/" + model["id"] + "/archive",
            json={
                "version": model["version"],
                "archived": True,
            },
        )
        assert result.status_code == 200, result.text
    path = BASE + "/" + channel["id"]
    response = await admin.api.request(
        "DELETE",
        path + "/models",
        json={
            "version": channel["version"],
            "models": [{"id": "bound"}],
        },
    )
    assert response.status_code == 200, response.text
    detail = (await admin.api.get(path)).json()
    refs = detail["binding_references"]
    assert len(refs) == 1 and refs[0]["model_id"] == model["id"]
    assert refs[0]["binding_id"] == model["bindings"][0]["binding_id"]
    assert not refs[0]["source_registered"]
    assert refs[0]["model_archived"] is archived_model
    assert refs[0]["health_state"] == ("model_archived" if archived_model else "model_disabled")
    async with env.sessions() as db:
        stored = await db.get(CatalogModel, UUID(model["id"]))
        assert (
            stored.configuration["operations"][0]["bindings"] == model["operations"][0]["bindings"]
        )


async def test_reference_projection_is_read_only_and_denied_to_members(env):
    admin = await env.client()
    channel = await create(admin, models=[{"id": "bound"}])
    model = await linked(admin, channel)
    member = await env.client(role="member", tenant=admin.tenant)
    path = BASE + "/" + channel["id"]
    assert (await member.api.get(path)).status_code == 403
    denied = await member.api.request(
        "DELETE",
        path + "/models",
        json={
            "version": 1,
            "models": [{"id": "bound"}],
        },
    )
    assert denied.status_code == 403 and "references" not in denied.text
    async with env.sessions() as db:
        before = await db.scalar(select(func.count()).select_from(AuditEvent))
    for _ in range(2):
        response = await admin.api.get(path)
        assert response.status_code == 200
        assert response.json()["binding_references"][0]["model_id"] == model["id"]
        assert "sealed_key" not in response.text and "test-secret" not in response.text
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(AuditEvent)) == before
        assert await db.scalar(select(func.count()).select_from(RouteHealth)) == 0
        assert (await db.get(ModelChannel, UUID(channel["id"]))).version == 1


async def test_latest_diagnostic_does_not_hide_unconfirmed_attempt(env):
    admin = await env.client()
    channel = await create(admin, models=[{"id": "bound"}])
    empty = await create(admin, name="No diagnostics")
    t = now()
    requests = [str(uuid4()), str(uuid4())]
    async with env.sessions() as db:
        for offset, request_id in enumerate(requests):
            db.add(
                AuditEvent(
                    tenant_id=admin.tenant.id,
                    actor_id=admin.user.id,
                    actor_name="Admin",
                    target_id=UUID(channel["id"]),
                    target_name=channel["name"],
                    action="llm.channel.test.start",
                    created_at=t + timedelta(seconds=offset),
                    details={
                        "request_id": request_id,
                        "model": "bound",
                        "operation": "chat",
                        "channel_version": "1",
                    },
                )
            )
        db.add(
            AuditEvent(
                tenant_id=admin.tenant.id,
                actor_id=admin.user.id,
                actor_name="Admin",
                target_id=UUID(channel["id"]),
                target_name=channel["name"],
                action="llm.channel.test.finish",
                result="success",
                created_at=t,
                details={
                    "request_id": requests[0],
                    "duration_ms": "120",
                    "output": "must-not-project",
                },
            )
        )
        await db.commit()
    path = BASE + "/" + channel["id"]
    detail = (await admin.api.get(path)).json()
    latest = detail["last_diagnostic"]
    assert latest["request_id"] == requests[1]
    assert latest["status"] == "unconfirmed" and latest["ok"] is None
    assert latest["duration_ms"] is None and not latest["stale"]
    listed = (await admin.api.get(BASE)).json()["items"]
    assert next(row for row in listed if row["id"] == channel["id"])["last_diagnostic"] == latest
    assert next(row for row in listed if row["id"] == empty["id"])["last_diagnostic"] is None
    async with env.sessions() as db:
        db.add(
            AuditEvent(
                tenant_id=admin.tenant.id,
                actor_id=admin.user.id,
                actor_name="Admin",
                target_id=UUID(channel["id"]),
                target_name=channel["name"],
                action="llm.channel.test.finish",
                result="failure",
                created_at=t + timedelta(seconds=2),
                details={
                    "request_id": requests[1],
                    "duration_ms": "47",
                    "output": "must-not-project",
                },
            )
        )
        await db.commit()
    response = await admin.api.get(path)
    assert "must-not-project" not in response.text
    assert response.json()["last_diagnostic"]["ok"] is False
    assert response.json()["last_diagnostic"]["duration_ms"] == 47
    await admin.api.put(path + "/status", json={"version": 1, "manual_enabled": False})
    assert (await admin.api.get(path)).json()["last_diagnostic"]["stale"] is True


async def test_concurrent_new_binding_and_remove_share_the_organization_lock(env):
    admin = await env.client()
    other = await env.client(tenant=admin.tenant)
    channel = await create(admin, models=[{"id": "bound"}])
    path = BASE + "/" + channel["id"]
    add, remove = await asyncio.gather(
        other.api.post(
            CATALOG,
            json={
                "name": "Concurrent",
                "slug": "concurrent",
                "operations": [
                    {
                        "kind": "chat",
                        "enabled": False,
                        "bindings": [
                            {
                                "channel_id": channel["id"],
                                "upstream_id": "bound",
                                "enabled": True,
                            }
                        ],
                    }
                ],
            },
        ),
        admin.api.request(
            "DELETE", path + "/models", json={"version": 1, "models": [{"id": "bound"}]}
        ),
    )
    assert (add.status_code, remove.status_code) in [(200, 409), (422, 200)]
    detail = (await admin.api.get(path)).json()
    assert bool(detail["models"]) == (add.status_code == 200)


async def test_removed_source_cannot_be_reenabled_through_an_existing_disabled_binding(env):
    admin = await env.client()
    channel = await create(admin, models=[{"id": "bound"}])
    model = await linked(admin, channel, enabled=False)
    removed = await admin.api.request(
        "DELETE",
        BASE + "/" + channel["id"] + "/models",
        json={
            "version": 1,
            "models": [{"id": "bound"}],
        },
    )
    assert removed.status_code == 200
    operations = model["operations"]
    operations[0]["bindings"][0]["enabled"] = True
    result = await admin.api.put(
        CATALOG + "/" + model["id"],
        json={
            "version": model["version"],
            "name": model["name"],
            "slug": model["slug"],
            "operations": operations,
        },
    )
    assert result.status_code == 422, result.text
    current = (await admin.api.get(CATALOG + "/" + model["id"])).json()
    assert current["version"] == model["version"]
    assert not current["operations"][0]["bindings"][0]["enabled"]
