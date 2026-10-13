"""MCP operational settings, tenant-scoped metadata and non-executing health probes."""

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastmcp import Context, FastMCP
from sqlalchemy import select
from test_mcp import create, listening, update
from test_mcp import env as mcp_env
from test_mcp import upstream as mcp_upstream

from app.modules.auth.service import now
from app.modules.mcp import health
from app.modules.mcp.credentials import SHARED
from app.modules.mcp.models import McpActivity, McpHealth
from app.modules.members.models import Membership

env = mcp_env
upstream = mcp_upstream

pytestmark = pytest.mark.asyncio


async def test_connection_options_validate_roundtrip_and_record_permissions(env, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    other = await env.client(joined=False)
    service = await create(
        admin,
        transport=transport,
        url=url,
        connection_options={"connect_timeout": 5, "request_timeout": 15, "total_timeout": 40},
    )
    assert service["connection_options"]["request_timeout"] == 15
    assert service["connection_options"]["health_enabled"] is False
    invalid = await admin.api.post(
        "/api/v1/mcp/services",
        json={
            "name": "invalid",
            "transport": "http",
            "url": url,
            "connection_options": {"request_timeout": 50, "total_timeout": 10},
        },
    )
    assert invalid.status_code == 422
    path = f"/api/v1/mcp/services/{service['id']}"
    assert (await admin.api.post(path + "/discover")).status_code == 200
    run = await admin.api.post(
        path + "/run", json={"kind": "tools", "key": "add", "arguments": {"a": 1, "b": 2}}
    )
    assert run.status_code == 200, run.text
    failed = await admin.api.post(
        path + "/run",
        json={"kind": "tools", "key": "add", "arguments": {"a": "do-not-store-this", "b": 2}},
    )
    assert failed.status_code == 422
    records = (await admin.api.get("/api/v1/mcp/activities?category=call")).json()
    assert records["total"] == 2
    assert {r["result"] for r in records["items"]} == {"success", "failed"}
    assert all(
        r["capability"] == "add" and r["request_id"] and r["duration_ms"] >= 0
        for r in records["items"]
    )
    assert "do-not-store-this" not in str(records)
    assert all("arguments" not in record for record in records["items"])
    filtered = (
        await admin.api.get(
            f"/api/v1/mcp/activities?category=call&service_id={service['id']}&result=success&q=add"
        )
    ).json()
    assert filtered["total"] == 1
    assert (await admin.api.get("/api/v1/mcp/activities?category=call&page=2")).json()[
        "items"
    ] == []
    assert (await member.api.get("/api/v1/mcp/activities?category=call")).status_code == 403
    assert (await other.api.get("/api/v1/mcp/activities?category=call")).status_code == 403
    exported = (await admin.api.get("/api/v1/mcp/export")).json()
    assert exported["services"][0]["connection_options"]["request_timeout"] == 15
    assert (await admin.api.get("/api/v1/mcp/activities?category=connection")).json()["total"] == 1
    assert (
        await admin.api.get("/api/v1/mcp/activities?category=call&since=2026-01-01T00:00:00")
    ).status_code == 422


async def due(env, service_id, owner=SHARED):
    async with env.sessions() as db:
        row = await db.get(McpHealth, (UUID(service_id), owner))
        row.next_check_at = now() - timedelta(seconds=1)
        await db.commit()


async def test_health_checks_stop_when_disabled_backoff_recover_and_do_not_change_tools(
    env, upstream, monkeypatch
):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin = await env.client()
    service = await create(
        admin, transport=transport, url=url, connection_options={"health_enabled": True}
    )
    sid = UUID(service["id"])
    assert not await health.probe(env.app, sid, SHARED)  # Master off.
    service = await update(admin, service, enabled=True)
    checks = await asyncio.gather(
        health.probe(env.app, sid, SHARED), health.probe(env.app, sid, SHARED)
    )
    assert checks.count(True) == 1
    assert (await admin.api.get(f"/api/v1/mcp/services/{sid}/capabilities")).json()["items"] == []
    async with env.sessions() as db:
        state = await db.get(McpHealth, (sid, SHARED))
        assert state.checked_at and not state.error
        assert state.next_check_at > now()
    original = health.headers_for_owner

    async def fail(*args):
        raise HTTPException(502, "secret-value-should-not-appear")

    monkeypatch.setattr(health, "headers_for_owner", fail)
    await due(env, service["id"])
    assert await health.probe(env.app, sid, SHARED)
    async with env.sessions() as db:
        state = await db.get(McpHealth, (sid, SHARED))
        assert state.failures == 1 and state.error
        assert state.next_check_at > now() + timedelta(seconds=100)
    monkeypatch.setattr(health, "headers_for_owner", original)
    await due(env, service["id"])
    assert await health.probe(env.app, sid, SHARED)
    logs = (await admin.api.get("/api/v1/mcp/activities?category=connection")).json()
    assert logs["total"] == 3 and logs["items"][0]["operation"] == "recovered"
    assert "secret-value" not in str(logs)
    service = await update(admin, service, enabled=False)
    await due(env, service["id"])
    assert not await health.probe(env.app, sid, SHARED)


async def test_health_personal_identity_and_paused_members(env, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    service = await create(
        admin,
        transport=transport,
        url=url,
        auth_mode="personal",
        credential_fields=[
            {"key": "token", "label": "Token", "header": "Authorization", "bearer": True}
        ],
        connection_options={"health_enabled": True},
    )
    service = await update(admin, service, enabled=True)
    sid = UUID(service["id"])
    for actor, token in [(admin, "person-a"), (member, "person-b")]:
        assert (
            await actor.api.put(
                f"/api/v1/mcp/services/{sid}/connection", json={"values": {"token": token}}
            )
        ).status_code == 200
    assert not await health.probe(env.app, sid, SHARED)
    assert await health.probe(env.app, sid, member.member.id)
    assert await health.probe(env.app, sid, admin.member.id)
    async with env.sessions() as db:
        logs = (await db.scalars(select(McpActivity).where(McpActivity.service_id == sid))).all()
        assert {log.owner_id for log in logs} == {admin.member.id, member.member.id}
        member_row = await db.get(Membership, member.member.id)
        member_row.status = "paused"
        await db.commit()
    await due(env, service["id"], member.member.id)
    assert not await health.probe(env.app, sid, member.member.id)


@pytest.mark.parametrize("reset,total,expected", [(False, 5, 504), (True, 5, 200), (True, 1, 504)])
async def test_real_tool_progress_extends_idle_timeout_but_not_total(env, reset, total, expected):
    upstream = FastMCP("progress")

    @upstream.tool
    async def slow(ctx: Context) -> str:
        for step in range(6):
            await asyncio.sleep(0.25)
            await ctx.report_progress(step + 1, 6)
        return "done"

    async with listening(upstream.http_app()) as base:
        env.provider.settings.mcp_allowed_private_origins = [base]
        admin = await env.client()
        service = await create(
            admin,
            transport="http",
            url=base + "/mcp",
            connection_options={
                "connect_timeout": 1,
                "request_timeout": 1,
                "total_timeout": total,
                "reset_on_progress": reset,
            },
        )
        path = f"/api/v1/mcp/services/{service['id']}"
        assert (await admin.api.post(path + "/discover")).status_code == 200
        response = await admin.api.post(
            path + "/run", json={"kind": "tools", "key": "slow", "arguments": {}}
        )
        assert response.status_code == expected, response.text
        logs = (await admin.api.get("/api/v1/mcp/activities?category=call")).json()
        assert logs["items"][0]["result"] == ("success" if expected == 200 else "timeout")
