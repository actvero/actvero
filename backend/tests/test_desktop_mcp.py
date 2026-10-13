"""Native API isolation and real MCP SDK protocol interoperability on disposable PostgreSQL."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from sqlalchemy import select
from test_desktop import bearer, login, native_client
from test_identity_access import env as identity_env
from test_mcp import create, update
from test_mcp import upstream as protocol_fixture

from app.modules.auth.service import now
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop_mcp.models import NativeOAuthAttempt, ResourceToken
from app.modules.mcp import credentials
from app.modules.mcp.models import McpActivity, McpConnection, McpService
from app.modules.members.models import Membership

env = identity_env
upstream = protocol_fixture
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/desktop/mcp"


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


async def token(api, root, resource="mcp:catalog"):
    r = await api.post(
        "/api/v1/desktop/resource-tokens", headers=bearer(root), json={"resource": resource}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def native(env, monkeypatch, api, web):
    root, _ = await login(env, monkeypatch, api, web)
    return root, await token(api, root)


async def test_catalog_scope_admin_no_bypass_and_revoke(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    closed = await create(admin)
    row = await create(admin, name="Open", display_name="Public")
    row = await update(admin, row, enabled=True)
    restricted = await create(
        admin, name="Restricted", audience="selected", member_ids=[str(member.member.id)]
    )
    restricted = await update(admin, restricted, enabled=True)
    async with native_client(env) as api:
        root, catalog = await native(env, monkeypatch, api, admin)
        headers = bearer(catalog)
        data = (await api.get(BASE + "/connectors", headers=headers)).json()
        assert [c["id"] for c in data["items"]] == [row["id"]]
        assert data["total"] == 1
        assert not any(
            k in data["items"][0] for k in ("url", "oauth", "member_ids", "credential_values")
        )
        assert (await api.get(BASE + "/connectors", headers=bearer(root))).status_code == 401
        assert (await admin.api.get(BASE + "/connectors", headers=headers)).status_code == 401
        assert (
            await api.get(BASE + "/connectors", headers={**headers, "origin": "https://evil.test"})
        ).status_code == 401
        assert (
            await api.get(BASE + "/connectors/" + closed["id"], headers=headers)
        ).status_code == 404
        assert (
            await api.get(BASE + "/connectors/" + restricted["id"], headers=headers)
        ).status_code == 404
        invocation = await token(api, root, "mcp:" + row["id"])
        assert (await api.get(BASE + "/connectors", headers=bearer(invocation))).status_code == 403
        assert (await api.get("/api/v1/desktop/me", headers=headers)).status_code == 401
        assert (await api.get("/api/v1/mcp/services", headers=headers)).status_code == 401
        async with env.sessions() as db:
            tokens = (await db.scalars(select(ResourceToken))).all()
            assert len(tokens) == 2 and all(t.token_hash != catalog["access_token"] for t in tokens)
        await api.post("/api/v1/desktop/logout", json={"refresh_token": root["refresh_token"]})
        assert (await api.get(BASE + "/connectors", headers=headers)).status_code == 401


async def test_protocol_sdk_all_capabilities_policy_and_records(env, monkeypatch, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, member = await env.client(), await env.client(role="member")
    row = await create(admin, transport=transport, url=url)
    path = "/api/v1/mcp/services/" + row["id"]
    assert (await admin.api.post(path + "/discover")).status_code == 200
    row = await update(admin, row, enabled=True)
    async with native_client(env) as api:
        root, catalog = await native(env, monkeypatch, api, member)
        invocation = await token(api, root, "mcp:" + row["id"])

        def factory(**kwargs):
            return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=env.app), **kwargs)

        gateway = StreamableHttpTransport(
            invocation["endpoint"], headers=bearer(invocation), httpx_client_factory=factory
        )
        async with Client(gateway, mode="legacy", timeout=10, cache=False) as client:
            assert client.protocol_version in {"2025-11-25", "2025-06-18", "2025-03-26"}
            assert "add" in [t.name for t in await client.list_tools()]
            result = await client.call_tool("add", {"a": 2, "b": 3})
            assert "5" in str(result)
            assert [p.name for p in await client.list_prompts()] == ["greet"]
            assert "Hello Ada" in str(await client.get_prompt("greet", {"name": "Ada"}))
            assert len(await client.list_resources()) == 1
            assert len(await client.list_resource_templates()) == 1
            assert "Guide content" in str(await client.read_resource("fixture://guide"))
            assert "Person Ada" in str(await client.read_resource("fixture://people/Ada"))
            await admin.api.put(
                path + "/policy", json={"kind": "tools", "key": "add", "enabled": False}
            )
            assert "add" not in [t.name for t in await client.list_tools()]
            with pytest.raises(Exception, match="未开放"):
                await client.call_tool("add", {"a": 2, "b": 3})
            await update(admin, row, enabled=False)
            with pytest.raises(Exception, match="404|Not Found"):
                await client.list_tools()
        async with env.sessions() as db:
            logs = (
                await db.scalars(select(McpActivity).where(McpActivity.source == "desktop"))
            ).all()
            assert logs and all(str(e.device_session_id) == root["device_session_id"] for e in logs)
            assert all(e.actor_id == member.user.id for e in logs)
            assert any(e.category == "call" for e in logs)
        assert (
            await api.get(BASE + "/connectors/" + row["id"], headers=bearer(catalog))
        ).status_code == 404


async def test_personal_connections_isolated_and_no_organization_write(env, monkeypatch, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, alice, bob = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    fields = [{"key": "token", "label": "Token", "header": "Authorization", "bearer": True}]
    row = await create(
        admin, transport=transport, url=url, auth_mode="personal", credential_fields=fields
    )
    path = "/api/v1/mcp/services/" + row["id"]
    await admin.api.put(path + "/connection", json={"values": {"token": "person-a"}})
    await admin.api.post(path + "/discover")
    row = await update(admin, row, enabled=True)
    async with native_client(env) as api:
        aroot, at = await native(env, monkeypatch, api, alice)
        broot, bt = await native(env, monkeypatch, api, bob)
        cp = BASE + "/connectors/" + row["id"] + "/connection"
        for t, value in ((at, "person-a"), (bt, "person-b")):
            saved = await api.put(cp, headers=bearer(t), json={"values": {"token": value}})
            assert saved.status_code == 200 and value not in saved.text
            assert saved.json()["status"] == "unverified"
            assert (await api.post(cp + "/verify", headers=bearer(t))).json()[
                "status"
            ] == "connected"
        for root, expected in ((aroot, "Alice"), (broot, "Bob")):
            inv = await token(api, root, "mcp:" + row["id"])
            r = await api.post(
                inv["endpoint"],
                headers={**bearer(inv), "accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "caller"},
                },
            )
            assert expected in r.text, r.text
        assert (await api.delete(cp, headers=bearer(at))).status_code == 200
        assert (await api.get(cp, headers=bearer(bt))).json()["status"] == "connected"
        assert (await api.get(cp, headers=bearer(at))).json()["status"] == "not_connected"
        organization = await create(
            admin,
            name="Org",
            transport=transport,
            url=url,
            auth_mode="organization",
            credential_fields=fields,
            credential_values={"token": "person-a"},
        )
        organization = await update(admin, organization, enabled=True)
        othercp = BASE + "/connectors/" + organization["id"] + "/connection"
        assert (
            await api.put(othercp, headers=bearer(at), json={"values": {"token": "attack"}})
        ).status_code == 409
        assert (await api.delete(othercp, headers=bearer(at))).status_code == 409
        org_inv = await token(api, aroot, "mcp:" + organization["id"])
        response = await api.post(
            org_inv["endpoint"],
            headers={**bearer(org_inv), "accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert response.json()["result"]["tools"] == []  # Native discovery cannot open policies.
        assert (
            await admin.api.post("/api/v1/mcp/services/" + organization["id"] + "/discover")
        ).status_code == 200
        response = await api.post(
            org_inv["endpoint"],
            headers={**bearer(org_inv), "accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "caller"}},
        )
        assert "Alice" in response.text, response.text
        assert "person-a" not in (await api.get(BASE + "/connectors", headers=bearer(at))).text


async def oauth_service(env):
    env.provider.settings.mcp_allowed_private_origins = ["http://127.0.0.1:9000"]
    admin = await env.client()
    row = await create(
        admin,
        transport="http",
        url="http://127.0.0.1:9000/mcp",
        auth_mode="oauth",
        oauth={
            "authorization_url": "http://127.0.0.1:9000/authorize",
            "token_url": "http://127.0.0.1:9000/token",
            "client_id": "fixture",
        },
    )
    return admin, await update(admin, row, enabled=True)


async def test_oauth_device_confirmation_replay_cancel_and_late_callback(env, monkeypatch):
    admin, row = await oauth_service(env)
    exchange = AsyncMock(
        return_value={"access_token": "upstream-private", "expires_at": 9999999999}
    )
    monkeypatch.setattr(credentials, "token_request", exchange)
    async with native_client(env) as api:
        root, catalog = await native(env, monkeypatch, api, admin)
        _, other = await native(env, monkeypatch, api, admin)
        headers = bearer(catalog)
        start = await api.post(
            BASE + "/connectors/" + row["id"] + "/oauth-attempts", headers=headers
        )
        assert start.status_code == 200, start.text
        data = start.json()
        params = parse_qs(urlsplit(data["authorization_url"]).query)
        assert params["code_challenge_method"] == ["S256"]
        attemptpath = BASE + "/oauth-attempts/" + data["id"]
        assert (await api.get(attemptpath, headers=bearer(other))).status_code == 404
        response = await api.get(
            BASE + "/oauth/callback", params={"state": params["state"][0], "code": "code"}
        )
        assert response.status_code == 200 and "upstream-private" not in response.text
        assert (await api.get(attemptpath, headers=headers)).json()[
            "status"
        ] == "awaiting_confirmation"
        async with env.sessions() as db:
            assert await db.get(McpConnection, (UUID(row["id"]), admin.member.id)) is None
        assert (await api.post(attemptpath + "/complete", headers=bearer(other))).status_code == 404
        assert (await api.post(attemptpath + "/complete", headers=headers)).json()[
            "status"
        ] == "completed"
        assert (await api.post(attemptpath + "/complete", headers=headers)).json()[
            "status"
        ] == "completed"
        assert (
            await api.get(
                BASE + "/oauth/callback", params={"state": params["state"][0], "code": "code"}
            )
        ).status_code == 400
        assert exchange.await_count == 1
        await api.delete(BASE + "/connectors/" + row["id"] + "/connection", headers=headers)
        # Cancellation wins even while the upstream token exchange is running.
        begun, proceed = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            begun.set()
            await proceed.wait()
            return {"access_token": "late-secret", "expires_at": 9999999999}

        monkeypatch.setattr(credentials, "token_request", delayed)
        data = (
            await api.post(BASE + "/connectors/" + row["id"] + "/oauth-attempts", headers=headers)
        ).json()
        state = parse_qs(urlsplit(data["authorization_url"]).query)["state"][0]
        late = asyncio.create_task(
            api.get(BASE + "/oauth/callback", params={"state": state, "code": "late"})
        )
        await asyncio.wait_for(begun.wait(), 5)
        cancelled = await api.delete(BASE + "/oauth-attempts/" + data["id"], headers=headers)
        assert cancelled.json()["status"] == "cancelled"
        proceed.set()
        await late
        assert (
            await api.post(BASE + "/oauth-attempts/" + data["id"] + "/complete", headers=headers)
        ).json()["status"] == "cancelled"
        async with env.sessions() as db:
            assert await db.get(McpConnection, (UUID(row["id"]), admin.member.id)) is None
            attempt = await db.get(NativeOAuthAttempt, UUID(data["id"]))
            assert attempt.pending_tokens is None and attempt.verifier is None


async def test_oauth_configuration_change_expiry_and_device_logout(env, monkeypatch):
    admin, row = await oauth_service(env)
    monkeypatch.setattr(
        credentials,
        "token_request",
        AsyncMock(return_value={"access_token": "private", "expires_at": 9999999999}),
    )
    async with native_client(env) as api:
        root, ct = await native(env, monkeypatch, api, admin)
        h = bearer(ct)
        sp = BASE + "/connectors/" + row["id"] + "/oauth-attempts"
        data = (await api.post(sp, headers=h)).json()
        state = parse_qs(urlsplit(data["authorization_url"]).query)["state"][0]
        await api.get(BASE + "/oauth/callback", params={"state": state, "code": "code"})
        row = await update(admin, row, description="changed")
        result = await api.post(BASE + "/oauth-attempts/" + data["id"] + "/complete", headers=h)
        assert result.json()["error_code"] == "connector_changed"
        data = (await api.post(sp, headers=h)).json()
        async with env.sessions() as db:
            a = await db.get(NativeOAuthAttempt, UUID(data["id"]))
            a.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await api.get(BASE + "/oauth-attempts/" + data["id"], headers=h)).json()[
            "status"
        ] == "expired"
        await api.post("/api/v1/desktop/logout", json={"refresh_token": root["refresh_token"]})
        assert (
            await api.post(BASE + "/oauth-attempts/" + data["id"] + "/complete", headers=h)
        ).status_code == 401


async def test_token_expiry_member_suspension_and_protocol_errors(env, monkeypatch):
    admin = await env.client()
    row = await update(admin, await create(admin), enabled=True)
    async with native_client(env) as api:
        root, catalog = await native(env, monkeypatch, api, admin)
        inv = await token(api, root, "mcp:" + row["id"])
        h = {**bearer(inv), "accept": "application/json, text/event-stream"}
        endpoint = inv["endpoint"]

        async def rpc(method, params=None):
            return await api.post(
                endpoint,
                headers=h,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            )

        assert (await rpc("ping")).json()["result"] == {}
        assert (await rpc("invented/method")).json()["error"]["code"] == -32601
        assert (await rpc("tools/call", {"name": 42})).json()["error"]["code"] == -32602
        assert (await api.get(endpoint, headers=h)).status_code == 405
        assert (
            await api.post(endpoint, headers={**h, "mcp-protocol-version": "invalid"}, json={})
        ).status_code == 400
        assert (
            await api.post(endpoint, headers={**h, "origin": "http://evil.test"}, json={})
        ).status_code == 403
        assert (await api.post(endpoint, headers=bearer(catalog), json={})).status_code == 403
        assert (
            await api.post(endpoint.replace(row["id"], str(uuid4())), headers=h, json={})
        ).status_code == 403
        async with env.sessions() as db:
            member = await db.get(Membership, admin.member.id)
            member.status = "paused"
            await db.commit()
        assert (await rpc("ping")).status_code == 403
        async with env.sessions() as db:
            member = await db.get(Membership, admin.member.id)
            member.status = "active"
            for t in (await db.scalars(select(ResourceToken))).all():
                t.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await rpc("ping")).status_code == 401


async def test_catalog_pagination_and_current_grants(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    async with env.sessions() as db:
        for i in range(23):
            db.add(
                McpService(
                    tenant_id=admin.tenant.id,
                    name=f"Catalog {i:02}",
                    transport="builtin",
                    enabled=True,
                )
            )
        await db.commit()
    async with native_client(env) as api:
        root, catalog = await native(env, monkeypatch, api, member)
        headers = bearer(catalog)
        one = (await api.get(BASE + "/connectors", headers=headers)).json()
        two = (await api.get(BASE + "/connectors?page=2", headers=headers)).json()
        assert one["total"] == two["total"] == 23
        assert len(one["items"]) == 20 and len(two["items"]) == 3
        assert not ({c["id"] for c in one["items"]} & {c["id"] for c in two["items"]})
        filtered = (await api.get(BASE + "/connectors?q=Catalog%2022", headers=headers)).json()
        assert filtered["total"] == 1
        sid = filtered["items"][0]["id"]
        inv = await token(api, root, "mcp:" + sid)
        async with env.sessions() as db:
            row = await db.get(McpService, UUID(sid))
            row.audience = "selected"
            row.member_ids = []
            await db.commit()
        assert (await api.get(BASE + "/connectors/" + sid, headers=headers)).status_code == 404
        r = await api.post(
            inv["endpoint"],
            headers={**bearer(inv), "accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        )
        assert r.status_code == 404


async def test_native_oauth_real_token_http_pkce_and_refusal(env, monkeypatch):
    from fastapi import FastAPI, Request
    from test_mcp import listening

    from app.modules.desktop.service import pkce

    provider = FastAPI()
    captured = []

    @provider.post("/token")
    async def exchange(request: Request):
        body = parse_qs((await request.body()).decode())
        captured.append(body)
        assert body["grant_type"] == ["authorization_code"]
        assert body["code"] == ["fixture-code"]
        return {"access_token": "fixture-secret", "token_type": "Bearer", "expires_in": 3600}

    async with listening(provider) as base:
        env.provider.settings.mcp_allowed_private_origins = [base]
        admin = await env.client()
        row = await create(
            admin,
            transport="http",
            url=base + "/mcp",
            auth_mode="oauth",
            oauth={
                "authorization_url": base + "/authorize",
                "token_url": base + "/token",
                "client_id": "fixture",
            },
        )
        row = await update(admin, row, enabled=True)
        async with native_client(env) as api:
            _, catalog = await native(env, monkeypatch, api, admin)
            headers = bearer(catalog)
            path = BASE + "/connectors/" + row["id"] + "/oauth-attempts"
            data = (await api.post(path, headers=headers)).json()
            params = parse_qs(urlsplit(data["authorization_url"]).query)
            callback = await api.get(
                BASE + "/oauth/callback",
                params={"state": params["state"][0], "code": "fixture-code"},
            )
            assert callback.status_code == 200
            assert pkce(captured[0]["code_verifier"][0]) == params["code_challenge"][0]
            assert captured[0]["redirect_uri"] == params["redirect_uri"]
            assert (
                await api.post(
                    BASE + "/oauth-attempts/" + data["id"] + "/complete", headers=headers
                )
            ).json()["status"] == "completed"
            async with env.sessions() as db:
                connection = await db.get(McpConnection, (UUID(row["id"]), admin.member.id))
                assert "fixture-secret" not in connection.sealed
                assert env.provider.unseal(connection.sealed)["access_token"] == "fixture-secret"
            data = (await api.post(path, headers=headers)).json()
            state = parse_qs(urlsplit(data["authorization_url"]).query)["state"][0]
            await api.get(
                BASE + "/oauth/callback", params={"state": state, "error": "access_denied"}
            )
            assert (await api.get(BASE + "/oauth-attempts/" + data["id"], headers=headers)).json()[
                "status"
            ] == "failed"
            assert len(captured) == 1
