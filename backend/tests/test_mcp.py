"""Real PostgreSQL + real loopback MCP HTTP/SSE; no production accounts/data."""

import asyncio
import base64
import hashlib
import socket
from contextlib import asynccontextmanager
from io import BytesIO
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI, Request
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware
from PIL import Image
from sqlalchemy import select
from sse_starlette.sse import AppStatus
from test_identity_access import env as identity_env

from app.modules.audit.models import AuditEvent
from app.modules.mcp.models import McpConnection, McpPolicy, McpSnapshot

env = identity_env

pytestmark = pytest.mark.asyncio


@asynccontextmanager
async def listening(app):
    # Each fixture is a new server; sse-starlette keeps shutdown state process-wide.
    # A previous HTTP fixture can otherwise immediately drain the next SSE server.
    AppStatus.should_exit = False
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 10)
        sock.close()


@pytest_asyncio.fixture(params=["http", "sse"])
async def upstream(request):
    app = FastMCP("Protocol fixture")

    @app.tool
    def add(a: int, b: int) -> int:
        return a + b

    @app.tool
    def caller() -> str:
        credential = get_http_headers(include={"authorization"}).get("authorization", "")
        # Two credentials resolve to distinct business identities, not token echoes.
        return {"Bearer person-a": "Alice", "Bearer person-b": "Bob"}.get(credential, "anonymous")

    @app.prompt
    def greet(name: str) -> str:
        return f"Hello {name}"

    @app.resource("fixture://guide")
    def guide() -> str:
        return "Guide content"

    @app.resource("fixture://people/{name}")
    def person(name: str) -> str:
        return f"Person {name}"

    @app.tool
    def alice_private() -> str:
        return "Alice-only tool"

    class PersonalDirectory(Middleware):
        async def on_list_tools(self, context, call_next):
            tools = await call_next(context)
            token = get_http_headers(include={"authorization"}).get("authorization")
            return [t for t in tools if t.name != "alice_private" or token == "Bearer person-a"]

    app.add_middleware(PersonalDirectory())
    transport = request.param
    async with listening(app.http_app(transport=transport)) as base:
        yield base, transport, base + ("/sse" if transport == "sse" else "/mcp")


async def create(actor, **data):
    r = await actor.api.post(
        "/api/v1/mcp/services", json={"name": "Fixture", "transport": "builtin", **data}
    )
    assert r.status_code == 200, r.text
    return r.json()


async def update(actor, service, **changes):
    body = {
        k: v
        for k, v in service.items()
        if k
        not in {
            "id",
            "configured",
            "checked_at",
            "error",
            "protocol",
            "counts",
            "health_checked_at",
            "health_error",
        }
    }
    r = await actor.api.put(f"/api/v1/mcp/services/{service['id']}", json={**body, **changes})
    assert r.status_code == 200, r.text
    return r.json()


async def test_builtin_content_closed_by_default_and_scope(env):
    admin = await env.client()
    member = await env.client(role="member")
    service = await create(admin, enabled=True)
    assert service["enabled"] is False
    path = f"/api/v1/mcp/services/{service['id']}"
    assert (await member.api.get("/api/v1/mcp/services")).json()["items"] == []
    assert (await member.api.get(path + "/capabilities")).status_code == 404
    assert (
        await member.api.post("/api/v1/mcp/services", json={"name": "bad", "transport": "builtin"})
    ).status_code == 403
    prompt = {
        "service_id": service["id"],
        "kind": "prompts",
        "name": "hello",
        "body": "Hello {{name}}",
        "arguments": ["name"],
    }
    r = await admin.api.post("/api/v1/mcp/contents", json=prompt)
    assert r.status_code == 200, r.text
    prompt_id = r.json()["id"]
    caps = (await admin.api.get(path + "/capabilities")).json()
    assert len(caps["items"]) == 1 and not caps["items"][0]["enabled"]
    run = {"kind": "prompts", "key": "hello", "arguments": {"name": "World"}}
    r = await admin.api.post(path + "/run", json=run)
    assert r.status_code == 200, r.text
    assert "Hello World" in r.text
    service = await update(
        admin, service, enabled=True, audience="selected", member_ids=[str(member.member.id)]
    )
    assert (await member.api.post(path + "/run", json=run)).status_code == 403
    assert (
        await admin.api.put(
            path + "/policy", json={"kind": "prompts", "key": "hello", "enabled": True}
        )
    ).status_code == 200
    assert (await member.api.post(path + "/run", json=run)).status_code == 200
    service = await update(admin, service, member_ids=[])
    assert (await member.api.post(path + "/run", json=run)).status_code == 404
    assert (await admin.api.delete("/api/v1/mcp/contents/" + prompt_id)).status_code == 200
    assert (await admin.api.post(path + "/run", json=run)).status_code == 409


async def test_legacy_builtin_can_be_edited_into_remote_service(env, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin = await env.client()
    member = await env.client(role="member")
    service = await create(
        admin,
        display_name="原展示名称",
        examples=["原使用示例"],
        audience="selected",
        member_ids=[str(member.member.id)],
    )
    path = f"/api/v1/mcp/services/{service['id']}"
    # The remote prompt has the same name: old approval must not carry over.
    response = await admin.api.post(
        "/api/v1/mcp/contents",
        json={
            "service_id": service["id"],
            "kind": "prompts",
            "name": "greet",
            "body": "Legacy {{name}}",
            "arguments": ["name"],
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    content_id = response.json()["id"]
    service = await update(admin, service, enabled=True)
    body = {
        k: v
        for k, v in service.items()
        if k
        not in {
            "id",
            "configured",
            "checked_at",
            "error",
            "protocol",
            "counts",
            "health_checked_at",
            "health_error",
        }
    }
    changes = {
        "transport": transport,
        "url": url,
        "auth_mode": "personal",
        "credential_fields": [
            {"key": "token", "label": "API Key", "header": "Authorization", "bearer": True}
        ],
    }
    assert (await member.api.put(path, json={**body, **changes})).status_code == 403
    assert (await admin.api.put(path, json={**body, **changes, "url": ""})).status_code == 422
    unchanged = (await admin.api.get(path + "/capabilities")).json()
    assert unchanged["items"][0]["enabled"] is True
    converted = await update(
        admin, service, **changes, name="Remote edited", description="New description"
    )
    assert converted["id"] == service["id"]
    assert converted["transport"] == transport and converted["url"] == url
    assert converted["name"] == "Remote edited" and converted["description"] == "New description"
    assert converted["enabled"] is False and converted["configured"] is False
    assert converted["audience"] == "selected"
    assert converted["member_ids"] == service["member_ids"]
    assert converted["display_name"] == "原展示名称" and converted["examples"] == ["原使用示例"]
    assert (await admin.api.get(path + "/capabilities")).json()["items"] == []
    assert (await member.api.get(path + "/capabilities")).status_code == 404
    # Retain authored content, but remote discovery/execution must never use it.
    saved = (await admin.api.get("/api/v1/mcp/contents")).json()["items"]
    assert any(item["id"] == content_id for item in saved)
    assert (
        await admin.api.put(path + "/connection", json={"values": {"token": "person-a"}})
    ).status_code == 200
    discovery = await admin.api.post(path + "/discover")
    assert discovery.status_code == 200, discovery.text
    assert discovery.json()["items"] and all(item["enabled"] for item in discovery.json()["items"])
    run = await admin.api.post(
        path + "/run", json={"kind": "prompts", "key": "greet", "arguments": {"name": "World"}}
    )
    assert run.status_code == 200 and "Hello World" in run.text and "Legacy" not in run.text
    assert (await admin.api.put(path, json={**body, **changes})).status_code == 409


async def test_real_protocol_all_capabilities(env, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    actor = await env.client()
    service = await create(actor, transport=transport, url=url)
    path = f"/api/v1/mcp/services/{service['id']}"
    r = await actor.api.post(path + "/discover")
    assert r.status_code == 200, r.text
    data = r.json()
    assert {x["kind"] for x in data["items"]} == {"tools", "prompts", "resources", "templates"}
    assert data["protocol"] == "2025-11-25"
    assert all(data["negotiated"].get(k) is not None for k in ("tools", "prompts", "resources"))
    assert all(c["enabled"] for c in data["items"])
    assert (await actor.api.get("/api/v1/mcp/services")).json()["items"][0]["enabled"] is False
    for body, expected in [
        ({"kind": "tools", "key": "add", "arguments": {"a": 2, "b": 3}}, "5"),
        ({"kind": "prompts", "key": "greet", "arguments": {"name": "World"}}, "Hello World"),
        ({"kind": "resources", "key": "fixture://guide"}, "Guide content"),
        (
            {
                "kind": "templates",
                "key": "fixture://people/{name}",
                "uri": "fixture://people/Alice",
            },
            "Person Alice",
        ),
    ]:
        r = await actor.api.post(path + "/run", json=body)
        assert r.status_code == 200, r.text
        assert expected in r.text
    assert (
        await actor.api.post(
            path + "/run",
            json={"kind": "tools", "key": "add", "arguments": {"a": "invalid", "b": 3}},
        )
    ).status_code == 422
    assert (
        await actor.api.post(path + "/run", json={"kind": "resources", "key": "file:///etc/passwd"})
    ).status_code == 409
    assert (
        await actor.api.post(
            path + "/run",
            json={"kind": "templates", "key": "fixture://people/{name}", "uri": "http://elsewhere"},
        )
    ).status_code == 422
    # Failed reconnect retains previously discovered capabilities, never a false empty success.
    env.provider.settings.mcp_allowed_private_origins = []
    assert (await actor.api.post(path + "/discover")).status_code == 502
    after = (await actor.api.get(path + "/capabilities")).json()
    assert len(after["items"]) == len(data["items"]) and after["error"]


async def test_personal_secrets_isolation_revocation_and_export(env, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    a, b = await env.client(), await env.client(role="member")
    service = await create(
        a,
        transport=transport,
        url=url,
        auth_mode="personal",
        credential_fields=[
            {"key": "token", "label": "Key", "header": "Authorization", "bearer": True}
        ],
    )
    service = await update(a, service, enabled=True)
    path = f"/api/v1/mcp/services/{service['id']}"
    for actor, secret in [(a, "person-a"), (b, "person-b")]:
        r = await actor.api.put(path + "/connection", json={"values": {"token": secret}})
        assert r.status_code == 200
        assert (await actor.api.post(path + "/discover")).status_code == 200
    assert (
        await a.api.put(path + "/policy", json={"kind": "tools", "key": "caller", "enabled": True})
    ).status_code == 200
    for actor, name in [(a, "Alice"), (b, "Bob")]:
        r = await actor.api.post(path + "/run", json={"kind": "tools", "key": "caller"})
        assert r.status_code == 200 and name in r.text, r.text
        assert "person-" not in (await actor.api.get("/api/v1/mcp/services")).text
    a_caps = (await a.api.get(path + "/capabilities")).json()["items"]
    b_caps = (await b.api.get(path + "/capabilities")).json()["items"]
    assert any(c["name"] == "alice_private" for c in a_caps)
    assert not any(c["name"] == "alice_private" for c in b_caps)
    export = await a.api.get("/api/v1/mcp/export")
    assert "person-a" not in export.text and "person-b" not in export.text
    async with env.sessions() as db:
        rows = (await db.scalars(select(McpConnection))).all()
        assert len(rows) == 2 and all("person-" not in r.sealed for r in rows)
        audit = (await db.scalars(select(AuditEvent))).all()
        assert all("person-" not in str(r.details) for r in audit)
    async with env.sessions() as db:
        from uuid import UUID

        rule = await db.get(McpPolicy, (UUID(service["id"]), "tools", "caller"))
        rule.definition_hash = "previous-contract"
        await db.commit()
    assert (
        await b.api.post(path + "/run", json={"kind": "tools", "key": "caller"})
    ).status_code == 409
    assert not any(
        c["key"] == "caller" for c in (await b.api.get(path + "/capabilities")).json()["items"]
    )
    assert (
        await a.api.put(path + "/policy", json={"kind": "tools", "key": "caller", "enabled": True})
    ).status_code == 200
    assert (await b.api.delete(path + "/connection")).status_code == 200
    assert (
        await b.api.post(path + "/run", json={"kind": "tools", "key": "caller"})
    ).status_code == 409
    assert (
        "Alice" in (await a.api.post(path + "/run", json={"kind": "tools", "key": "caller"})).text
    )
    assert not any(
        c["key"] == "caller" for c in (await b.api.get(path + "/capabilities")).json()["items"]
    )
    async with env.sessions() as db:
        member = await db.get(type(b.member), b.member.id)
        member.status = "paused"
        await db.commit()
    assert (await b.api.get("/api/v1/mcp/services")).status_code == 403


async def test_network_guards_and_atomic_import(env):
    admin = await env.client()
    for url in [
        "http://127.0.0.1:5195/api/v1/auth/session",
        "https://user:secret@example.com/mcp",
        "https://example.com/mcp?token=secret",
        "https://169.254.169.254/latest/meta-data/",
    ]:
        r = await admin.api.post("/api/v1/mcp/services", json={"name": "bad", "url": url})
        assert r.status_code == 422, r.text
    r = await admin.api.post(
        "/api/v1/mcp/import",
        json={
            "services": [
                {"name": "valid", "transport": "builtin"},
                {"name": "invalid", "url": "http://127.0.0.1"},
            ]
        },
    )
    assert r.status_code == 422
    assert (await admin.api.get("/api/v1/mcp/services")).json()["items"] == []
    admin.api.headers.pop("x-csrf-token")
    assert (
        await admin.api.post("/api/v1/mcp/services", json={"name": "valid", "transport": "builtin"})
    ).status_code == 403


async def test_builtin_resources_and_config_conflicts(env):
    a = await env.client()
    s = await create(a)
    path = f"/api/v1/mcp/services/{s['id']}"
    r = await a.api.post(
        "/api/v1/mcp/contents",
        json={
            "service_id": s["id"],
            "kind": "resources",
            "name": "guide",
            "body": "<script>literal text</script>",
            "enabled": True,
        },
    )
    assert r.status_code == 200, r.text
    uri = "actvero://resources/" + r.json()["id"]
    result = await a.api.post(path + "/run", json={"kind": "resources", "key": uri})
    assert result.status_code == 200 and "literal text" in result.text
    await update(a, s, enabled=True)
    conflict = await a.api.put(
        path,
        json={
            k: v
            for k, v in s.items()
            if k
            in {
                "name",
                "description",
                "transport",
                "url",
                "enabled",
                "audience",
                "member_ids",
                "auth_mode",
                "credential_fields",
                "oauth",
                "version",
            }
        },
    )
    assert conflict.status_code == 409
    assert (await a.api.delete(path)).status_code == 200
    async with env.sessions() as db:
        assert not (await db.scalars(select(McpSnapshot))).all()


async def test_oauth_state_pkce_refresh_and_session_binding(env):
    app = FastAPI()
    exchanges = []

    @app.post("/token")
    async def token(request: Request):
        data = dict(await request.form())
        exchanges.append(data)
        if data["grant_type"] == "authorization_code":
            assert len(data["code_verifier"]) >= 43
        return {
            "access_token": "oauth-private-token",
            "token_type": "Bearer",
            "refresh_token": "refresh-private",
            "expires_in": 0,
        }

    @app.get("/authorize")
    async def authorize():
        return {}

    async with listening(app) as base:
        env.provider.settings.mcp_allowed_private_origins = [base]
        a, b = await env.client(), await env.client(role="member")
        s = await create(
            a,
            transport="http",
            url=base + "/mcp",
            auth_mode="oauth",
            oauth={
                "authorization_url": base + "/authorize",
                "token_url": base + "/token",
                "client_id": "fixture",
                "scopes": "read",
            },
        )
        s = await update(a, s, enabled=True)
        path = f"/api/v1/mcp/services/{s['id']}"
        r = await a.api.post(path + "/oauth")
        assert r.status_code == 200, r.text
        params = parse_qs(urlsplit(r.json()["url"]).query)
        assert params["code_challenge_method"] == ["S256"]
        callback = "/api/v1/mcp/oauth/callback?" + urlencode_for(params["state"][0])
        assert (await b.api.get(callback)).status_code == 400
        assert (await a.api.get(callback)).status_code == 303
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(exchanges[0]["code_verifier"].encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        assert challenge == params["code_challenge"][0]
        assert (await a.api.get(callback)).status_code == 400
        # Discovery refreshes expired tokens even if the fixture is not an MCP endpoint.
        assert (await a.api.post(path + "/discover")).status_code == 502
        assert exchanges[-1]["grant_type"] == "refresh_token"
        assert "oauth-private-token" not in (await a.api.get("/api/v1/mcp/services")).text
        assert (await a.api.delete(path + "/connection")).status_code == 200
        assert (await a.api.post(path + "/discover")).status_code == 409


def urlencode_for(state):
    from urllib.parse import urlencode

    return urlencode({"state": state, "code": "test-code"})


async def test_dns_rebinding_and_redirects_never_leave_approved_origin(env, monkeypatch):
    from unittest.mock import AsyncMock

    import httpx2
    from fastapi import HTTPException

    from app.modules.mcp.network import PinnedTransport, resolve

    settings = env.provider.settings
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(
        loop,
        "getaddrinfo",
        AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]),
    )
    with pytest.raises(HTTPException):
        await resolve("https://public.example/mcp", settings)
    transport = PinnedTransport("https://public.example/mcp", settings)
    try:
        with pytest.raises(HTTPException):
            await transport.handle_async_request(
                httpx2.Request(
                    "POST", "https://other.example/mcp", headers={"authorization": "private"}
                )
            )
    finally:
        await transport.aclose()


async def test_presentation_preserves_credentials_policy_and_grants(env, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin = await env.client()
    member = await env.client(role="member")
    s = await create(
        admin,
        transport=transport,
        url=url,
        auth_mode="organization",
        credential_fields=[
            {"key": "token", "label": "API Key", "header": "Authorization", "bearer": True}
        ],
        credential_values={"token": "presentation-private-value"},
        audience="selected",
        member_ids=[str(member.member.id)],
    )
    path = f"/api/v1/mcp/services/{s['id']}"
    assert s["configured"] and "presentation-private-value" not in str(s)
    await admin.api.post(path + "/discover")
    await admin.api.put(path + "/policy", json={"kind": "tools", "key": "add", "enabled": True})
    s = await update(admin, s, enabled=True)
    image = BytesIO()
    Image.new("RGB", (32, 32), (24, 80, 160)).save(image, format="PNG")
    payload = {
        "version": s["version"],
        "display_name": "连接器名称",
        "description": "同一份简介",
        "examples": ["帮我计算总数"],
        "icon": "data:image/png;base64," + base64.b64encode(image.getvalue()).decode(),
    }
    assert (await member.api.put(path + "/presentation", json=payload)).status_code == 403
    response = await admin.api.put(path + "/presentation", json=payload)
    assert response.status_code == 200, response.text
    changed = response.json()
    assert changed["configured"] and changed["enabled"] and changed["checked_at"]
    assert changed["audience"] == "selected" and changed["member_ids"] == [str(member.member.id)]
    assert changed["name"] == "Fixture" and changed["display_name"] == "连接器名称"
    saved_icon = changed["icon"]
    assert saved_icon.startswith("data:image/webp;base64,")
    assert (await admin.api.get("/api/v1/mcp/services")).json()["items"][0]["icon"] == saved_icon
    assert (await admin.api.put(path + "/presentation", json=payload)).status_code == 409
    changed = await update(
        admin,
        changed,
        credential_fields=[
            {"key": "token", "label": "我的密钥", "header": "Authorization", "bearer": True}
        ],
    )
    assert changed["configured"] and changed["enabled"] and changed["checked_at"]
    assert changed["icon"] == saved_icon
    run = await member.api.post(
        path + "/run", json={"kind": "tools", "key": "add", "arguments": {"a": 1, "b": 2}}
    )
    assert run.status_code == 200, run.text
    bad = await admin.api.put(
        path + "/presentation",
        json={
            **payload,
            "version": changed["version"],
            "icon": "data:image/svg+xml;base64,PHN2Zy8+",
        },
    )
    assert bad.status_code == 422


async def test_import_preview_redacts_and_is_atomic(env, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin = await env.client()
    member = await env.client(role="member")
    raw = {
        "mcpServers": {
            "Imported": {
                "type": transport,
                "url": url,
                "headers": {"Authorization": "Bearer import-private-value"},
            }
        }
    }
    preview = await admin.api.post("/api/v1/mcp/import/preview", json={"configuration": raw})
    assert preview.status_code == 200 and preview.json()["valid"], preview.text
    assert "import-private-value" not in preview.text
    assert preview.json()["items"][0]["has_credentials"]
    assert (await admin.api.get("/api/v1/mcp/services")).json()["items"] == []
    assert (
        await member.api.post("/api/v1/mcp/import/preview", json={"configuration": raw})
    ).status_code == 403
    mixed = {
        "configuration": {
            "mcpServers": {**raw["mcpServers"], "Bad": {"command": "npx", "args": ["example"]}}
        }
    }
    preview = await admin.api.post("/api/v1/mcp/import/preview", json=mixed)
    assert not preview.json()["valid"]
    assert (await admin.api.post("/api/v1/mcp/import", json=mixed)).status_code == 422
    assert (await admin.api.get("/api/v1/mcp/services")).json()["items"] == []
    imported = await admin.api.post("/api/v1/mcp/import", json={"configuration": raw})
    assert imported.status_code == 200, imported.text
    service = imported.json()["items"][0]
    assert service["configured"] and not service["enabled"]
    assert "import-private-value" not in imported.text
    await create(admin, name="Legacy content", transport="builtin", url="")
    exported = await admin.api.get("/api/v1/mcp/export")
    assert "import-private-value" not in exported.text
    assert [s["name"] for s in exported.json()["services"]] == ["Imported"]
    copy_config = exported.json()
    copy_config["services"][0]["name"] = "Imported copy"
    check = await admin.api.post("/api/v1/mcp/import/preview", json={"configuration": copy_config})
    assert check.status_code == 200 and check.json()["valid"], check.text
    assert not check.json()["items"][0]["has_credentials"]
    assert (
        await admin.api.post("/api/v1/mcp/import", json={"configuration": raw})
    ).status_code == 409
    async with env.sessions() as db:
        connection = (await db.scalars(select(McpConnection))).one()
        assert "import-private-value" not in connection.sealed
        assert env.provider.unseal(connection.sealed) == {"credential_1": "import-private-value"}
        audits = (await db.scalars(select(AuditEvent))).all()
        assert "import-private-value" not in str([a.__dict__ for a in audits])


async def test_import_preview_and_confirm_use_deployment_public_dns(env, monkeypatch):
    from unittest.mock import AsyncMock

    from app.modules.mcp import network

    admin = await env.client()
    env.provider.settings.mcp_public_dns = "cloudflare"
    resolver = AsyncMock(return_value=["1.0.0.1"])
    monkeypatch.setattr(network, "public_dns", resolver)
    raw = {
        "configuration": {
            "mcpServers": {"公网测试": {"type": "http", "url": "https://public.example/mcp"}}
        }
    }
    preview = await admin.api.post("/api/v1/mcp/import/preview", json=raw)
    assert preview.status_code == 200 and preview.json()["valid"]
    # A DNS change between preview and confirmation must still prevent import.
    resolver.return_value = ["127.0.0.1"]
    denied = await admin.api.post("/api/v1/mcp/import", json=raw)
    assert denied.status_code == 422
    assert (await admin.api.get("/api/v1/mcp/services")).json()["items"] == []
    resolver.return_value = ["1.0.0.1"]
    imported = await admin.api.post("/api/v1/mcp/import", json=raw)
    assert imported.status_code == 200
    items = (await admin.api.get("/api/v1/mcp/services")).json()["items"]
    assert len(items) == 1 and not items[0]["enabled"]
    assert items[0]["url"] == "https://public.example/mcp"


async def test_first_catalog_on_master_off_refresh_preserves_choices(env, upstream, monkeypatch):
    from copy import deepcopy
    from uuid import UUID

    from sqlalchemy import delete

    from app.modules.mcp import service as logic
    from app.modules.mcp.models import McpService

    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin = await env.client()
    imported = await admin.api.post(
        "/api/v1/mcp/import",
        json={"configuration": {"mcpServers": {"initial": {"type": transport, "url": url}}}},
    )
    assert imported.status_code == 200
    service = imported.json()["items"][0]
    path = f"/api/v1/mcp/services/{service['id']}"
    first = (await admin.api.post(path + "/discover")).json()["items"]
    assert first and all(c["enabled"] for c in first)
    assert not service["enabled"]
    await admin.api.put(path + "/policy", json={"kind": "tools", "key": "add", "enabled": False})
    service = await update(admin, service, enabled=True)
    service = await update(admin, service, enabled=False)
    original = logic.discover

    async def changed(client):
        entries = await original(client)
        for c in entries:
            if c["key"] == "caller":
                c["definition"]["inputSchema"] = {
                    "type": "object",
                    "properties": {"extra": {"type": "string"}},
                }
        added = deepcopy(next(c for c in entries if c["key"] == "add"))
        added.update(key="new_tool", name="new_tool")
        entries.append(added)
        return entries

    monkeypatch.setattr(logic, "discover", changed)
    for reset in (False, True):
        if reset:
            async with env.sessions() as db:
                row = await db.get(McpService, UUID(service["id"]))
                assert row.catalog_initialized
                await db.execute(delete(McpSnapshot).where(McpSnapshot.service_id == row.id))
                await db.commit()
        refreshed = (await admin.api.post(path + "/discover")).json()["items"]
        by_key = {c["key"]: c for c in refreshed}
        assert not by_key["add"]["enabled"]
        assert not by_key["caller"]["enabled"]
        assert not by_key["new_tool"]["enabled"]
        assert by_key["greet"]["enabled"]
        assert not (await admin.api.get("/api/v1/mcp/services")).json()["items"][0]["enabled"]


async def test_member_discovery_cannot_enable_first_catalog(env, upstream):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, member = await env.client(), await env.client(role="member")
    service = await create(admin, transport=transport, url=url)
    service = await update(admin, service, enabled=True)
    path = f"/api/v1/mcp/services/{service['id']}"
    discovered = await member.api.post(path + "/discover")
    assert discovered.status_code == 200 and discovered.json()["items"] == []
    assert (
        await member.api.post(
            path + "/run", json={"kind": "tools", "key": "add", "arguments": {"a": 1, "b": 2}}
        )
    ).status_code == 403
