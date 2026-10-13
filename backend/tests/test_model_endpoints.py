"""The endpoint view names only public platform paths and reads no upstream."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel

from app.modules.auth.service import now
from app.modules.llm import routing
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import CatalogModel, RouteHealth
from app.modules.llm.providers.sdk_router import Gateway

pytestmark = pytest.mark.asyncio
env = identity_env
BASE = "/api/v1/llm/models"


async def test_endpoint_projection_is_admin_only_and_has_only_served_paths(env) -> None:
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    channel = await create_channel(admin, models=[{"id": "upstream"}])
    created = await admin.api.post(
        BASE,
        json={
            "slug": "public-chat",
            "name": "Public chat",
            "operations": [
                {
                    "kind": "chat",
                    "enabled": False,
                    "channel_id": channel["id"],
                    "upstream_id": "upstream",
                    "bindings": [
                        {"channel_id": channel["id"], "upstream_id": "upstream", "enabled": False}
                    ],
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    path = BASE + "/" + created.json()["id"] + "/endpoints"
    assert (await member.api.get(path)).status_code == 403
    projected = await admin.api.get(path)
    assert projected.status_code == 200, projected.text
    data = projected.json()
    assert data["member_authorization"] == "not_evaluated"
    assert data["slug"] == "public-chat"
    assert {item["operation"] for item in data["endpoints"]} == {
        "chat",
        "embedding",
        "rerank",
        "image_generation",
        "speech",
        "transcription",
    }
    chat = data["endpoints"][0]
    assert chat["method"] == "POST" and chat["path"] == "/api/llm/v1/chat/completions"
    assert not chat["open"]
    assert {"model_closed", "operation_closed", "binding_closed"} <= set(chat["reasons"])
    assert chat["example"]["model"] == "public-chat"
    assert all(not item["open"] for item in data["endpoints"][1:])
    assert "responses" not in projected.text
    assert "upstream" not in projected.text
    assert "test-secret" not in projected.text


async def test_declared_responses_does_not_create_a_platform_endpoint(env) -> None:
    admin = await env.client()
    channel = await create_channel(
        admin, models=[{"id": "upstream"}], declared_apis=["chat_completions", "responses"]
    )
    created = await admin.api.post(
        BASE,
        json={
            "slug": "response-declared",
            "name": "Response declared",
            "operations": [
                {
                    "kind": "chat",
                    "bindings": [{"channel_id": channel["id"], "upstream_id": "upstream"}],
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    response = await admin.api.get(BASE + "/" + created.json()["id"] + "/endpoints")
    assert response.status_code == 200, response.text
    assert all("responses" not in item["path"] for item in response.json()["endpoints"])


async def test_open_chat_endpoint_tracks_platform_route_state(env) -> None:
    admin = await env.client()
    channel = await create_channel(admin, models=[{"id": "upstream"}])
    created = await admin.api.post(
        BASE,
        json={
            "slug": "ready-chat",
            "name": "Ready chat",
            "access": {"enabled": True, "audience": "organization"},
            "operations": [
                {
                    "kind": "chat",
                    "enabled": True,
                    "channel_id": channel["id"],
                    "upstream_id": "upstream",
                    "context_window": 1000,
                    "max_output": 100,
                    "budget_price": {"currency": "USD", "input": "1", "output": "2"},
                    "bindings": [
                        {"channel_id": channel["id"], "upstream_id": "upstream", "enabled": True}
                    ],
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    path = BASE + "/" + created.json()["id"] + "/endpoints"
    before = (await admin.api.get(path)).json()
    assert before["endpoints"][0]["open"] is True
    assert before["endpoints"][0]["reasons"] == []
    assert before["member_authorization"] == "not_evaluated"
    archived = await admin.api.put(
        "/api/v1/llm/channels/" + channel["id"] + "/archive",
        json={"version": channel["version"], "archived": True},
    )
    assert archived.status_code == 200, archived.text
    after = (await admin.api.get(path)).json()
    assert after["endpoints"][0]["open"] is False
    assert "channel_archived" in after["endpoints"][0]["reasons"]


async def test_auto_endpoint_is_read_only_across_unverified_and_probing(env, monkeypatch) -> None:
    admin = await env.client()
    channel = await create_channel(admin, models=[{"id": "upstream"}])
    created = await admin.api.post(
        BASE,
        json={
            "slug": "auto-chat",
            "name": "Auto chat",
            "operations": [
                {
                    "kind": "chat",
                    "routing": {"mode": "auto", "model_revision": "rev"},
                    "bindings": [
                        {
                            "channel_id": channel["id"],
                            "upstream_id": "upstream",
                            "enabled": True,
                            "compatibility_key": "rev",
                        }
                    ],
                }
            ],
        },
    )
    assert created.status_code == 200, created.text
    model_id = UUID(created.json()["id"])
    path = BASE + "/" + str(model_id) + "/endpoints"
    async with env.sessions() as db:
        model = await db.get(CatalogModel, model_id)
        config_before = deepcopy(model.configuration)
        version_before = model.version
    choose = AsyncMock(side_effect=AssertionError("GET must not select a route"))
    monkeypatch.setattr(Gateway, "register", choose)
    first = (await admin.api.get(path)).json()
    assert first["endpoints"][0]["open"] is False
    assert "route_unverified" not in first["endpoints"][0]["reasons"]
    choose.assert_not_called()
    async with env.sessions() as db:
        model = await db.get(CatalogModel, model_id)
        assert model.configuration == config_before and model.version == version_before
        binding = CatalogInput.model_validate(model.configuration).for_operation("chat").bindings[0]
        route_key = routing.health_key(admin.tenant.id, model_id, "chat", binding)
        assert await db.get(RouteHealth, route_key) is None
        # Existing health belongs to the same current configuration; GET may
        # describe its probe but must never claim or extend the lease.
        from app.modules.llm.models import ModelChannel

        source = await db.get(ModelChannel, UUID(channel["id"]))
        fingerprint = routing.fingerprint(
            CatalogInput.model_validate(model.configuration).for_operation("chat"),
            binding,
            source,
        )
        deadline = now() + timedelta(seconds=90)
        db.add(
            RouteHealth(
                id=route_key,
                tenant_id=admin.tenant.id,
                fingerprint=fingerprint,
                tested_at=now(),
                probe_until=deadline,
                failures=0,
                blocked=False,
            )
        )
        await db.commit()
    second = (await admin.api.get(path)).json()
    assert "route_probing" not in second["endpoints"][0]["reasons"]
    choose.assert_not_called()
    async with env.sessions() as db:
        model = await db.get(CatalogModel, model_id)
        health = await db.get(RouteHealth, route_key)
        assert model.configuration == config_before and model.version == version_before
        assert health.probe_until == deadline and health.failures == 0


@pytest.mark.parametrize("blocked", [False, True])
async def test_list_summary_matches_detail_without_per_binding_health_reads(
    env, monkeypatch, blocked
):
    from sqlalchemy import event, func, select

    from app.modules.audit.models import AuditEvent
    from app.modules.llm.models import ModelChannel

    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    channel = await create_channel(admin, models=[{"id": "upstream"}])
    ids = []
    for index in range(3):
        response = await admin.api.post(
            BASE,
            json={
                "slug": f"summary-{index}",
                "name": f"Summary {index}",
                "access": {"enabled": True, "audience": "administrators"},
                "operations": [
                    {
                        "kind": "chat",
                        "enabled": True,
                        "channel_id": channel["id"],
                        "upstream_id": "upstream",
                        "context_window": 1000,
                        "max_output": 100,
                        "budget_price": {"currency": "USD", "input": "1", "output": "2"},
                        "bindings": [
                            {
                                "channel_id": channel["id"],
                                "upstream_id": "upstream",
                                "enabled": True,
                            }
                        ],
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        ids.append(response.json()["id"])
    async with env.sessions() as db:
        source = await db.get(ModelChannel, UUID(channel["id"]))
        if blocked:
            db.add(
                RouteHealth(
                    id=routing.credential_key(source),
                    tenant_id=admin.tenant.id,
                    fingerprint=routing.credential_fingerprint(source),
                    blocked=True,
                    failures=1,
                )
            )
            await db.commit()
        audit_before = await db.scalar(select(func.count()).select_from(AuditEvent))
        health_before = await db.scalar(select(func.count()).select_from(RouteHealth))
    choose = AsyncMock(side_effect=AssertionError("list projection cannot choose or send"))
    monkeypatch.setattr(Gateway, "register", choose)
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "FROM llm_route_health" in statement:
            statements.append(statement)

    engine = env.app.state.database.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = await admin.api.get(BASE)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert len(statements) == 1  # One scoped health snapshot for all three rows.
    assert response.json()["total"] == 3
    for item in response.json()["items"]:
        summary = item["endpoint_summary"]
        assert summary == {
            "configured_count": 1,
            "ready_count": 1,
            "reasons": [],
            "member_authorization": "not_evaluated",
        }
        detail = (await admin.api.get(BASE + "/" + item["id"])).json()
        assert detail["endpoint_summary"] == summary
        endpoints = (await admin.api.get(BASE + "/" + item["id"] + "/endpoints")).json()
        assert endpoints["endpoints"][0]["open"] is True
        assert endpoints["endpoints"][0]["stream_declaration"] == "unknown"
        assert "upstream" not in str(summary) and "test-secret" not in str(summary)
    assert (await member.api.get(BASE)).status_code == 403
    choose.assert_not_called()
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(RouteHealth)) == health_before
        assert await db.scalar(select(func.count()).select_from(AuditEvent)) == audit_before
        for model_id in ids:
            assert (await db.get(CatalogModel, UUID(model_id))).version == 1


async def test_empty_operation_draft_has_no_phantom_endpoint_summary(env):
    admin = await env.client()
    created = await admin.api.post(
        BASE, json={"slug": "empty-draft", "name": "Empty", "operations": []}
    )
    assert created.status_code == 200, created.text
    model_id = created.json()["id"]
    summary = (await admin.api.get(BASE + "/" + model_id)).json()["endpoint_summary"]
    assert summary == {
        "configured_count": 0,
        "ready_count": 0,
        "reasons": [],
        "member_authorization": "not_evaluated",
    }
    archived = await admin.api.put(
        BASE + "/" + model_id + "/archive", json={"version": 1, "archived": True}
    )
    assert archived.status_code == 200, archived.text
    listing = (await admin.api.get(BASE + "?state=archived")).json()
    assert listing["items"][0]["endpoint_summary"] == summary
