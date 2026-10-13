"""Real Bearer-protected upstream with isolated platform identities/schema.

Only the Keycloak identity exchange is stubbed by the shared fixture. MCP HTTP,
platform credential storage, resource tokens and authorization are real code.
"""

import importlib.util
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from test_desktop import bearer, native_client
from test_desktop_mcp import BASE, native, token
from test_desktop_mcp import identity as native_identity
from test_identity_access import env as identity_env
from test_mcp import create, listening, update

env = identity_env
identity = native_identity
pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def protected_upstream():
    path = Path(__file__).resolve().parents[2] / "scripts/mcp_lab.py"
    spec = importlib.util.spec_from_file_location("mcp_lab", path)
    assert spec and spec.loader
    lab = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lab)
    app = lab.LabBearerAuth(
        lab.create_server("AUTH", authenticated=True).http_app(stateless_http=True)
    )
    async with listening(app) as base:
        yield base, base + "/mcp"


async def test_protected_upstream_personal_and_organization_identity(
    env, monkeypatch, protected_upstream
):
    base, url = protected_upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    async with httpx.AsyncClient() as direct:
        for value in (None, "Bearer invalid", "Basic ds-lab-alice"):
            headers = {"Authorization": value} if value else {}
            assert (await direct.post(url, headers=headers, json={})).status_code == 401
    admin, alice, bob = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    fields = [{"key": "token", "label": "测试凭据", "header": "Authorization", "bearer": True}]
    row = await create(
        admin,
        name="personal-auth-lab",
        url=url,
        transport="http",
        auth_mode="personal",
        credential_fields=fields,
    )
    path = "/api/v1/mcp/services/" + row["id"]
    assert (
        await admin.api.put(path + "/connection", json={"values": {"token": "ds-lab-alice"}})
    ).status_code == 200
    assert (await admin.api.post(path + "/discover")).status_code == 200
    row = await update(admin, row, enabled=True)
    async with native_client(env) as api:
        aroot, acatalog = await native(env, monkeypatch, api, alice)
        broot, bcatalog = await native(env, monkeypatch, api, bob)
        ainvoke = await token(api, aroot, "mcp:" + row["id"])
        binvoke = await token(api, broot, "mcp:" + row["id"])
        cp = BASE + "/connectors/" + row["id"] + "/connection"

        async def call(invocation):
            return await api.post(
                invocation["endpoint"],
                headers={**bearer(invocation), "Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "who_am_i", "arguments": {}},
                },
            )

        # Missing personal binding must never inherit the administrator's Alice binding.
        assert "result" not in (await call(ainvoke)).json()
        await api.put(cp, headers=bearer(acatalog), json={"values": {"token": "wrong-lab-token"}})
        assert (await api.post(cp + "/verify", headers=bearer(acatalog))).status_code != 200
        assert "result" not in (await call(ainvoke)).json()
        for catalog, secret in ((acatalog, "ds-lab-alice"), (bcatalog, "ds-lab-bob")):
            saved = await api.put(cp, headers=bearer(catalog), json={"values": {"token": secret}})
            assert saved.status_code == 200 and secret not in saved.text
            assert (await api.post(cp + "/verify", headers=bearer(catalog))).status_code == 200
        for invocation, expected in ((ainvoke, "Alice"), (binvoke, "Bob")):
            result = (await call(invocation)).json()["result"]
            assert expected in str(result) and "ds-lab-" not in str(result)
        # The catalog credential cannot execute capabilities at a service endpoint.
        crossed = {**acatalog, "endpoint": ainvoke["endpoint"]}
        assert (await call(crossed)).status_code == 403
        assert (await api.delete(cp, headers=bearer(acatalog))).status_code == 200
        assert "result" not in (await call(ainvoke)).json()
        assert "Bob" in (await call(binvoke)).text
        # Explicit organization binding is shared by design, not an implicit fallback.
        org = await create(
            admin,
            name="organization-auth-lab",
            url=url,
            transport="http",
            auth_mode="organization",
            credential_fields=fields,
            credential_values={"token": "ds-lab-bob"},
        )
        assert (
            await admin.api.post("/api/v1/mcp/services/" + org["id"] + "/discover")
        ).status_code == 200
        org = await update(admin, org, enabled=True)
        org_invoke = await token(api, aroot, "mcp:" + org["id"])
        assert "Bob" in (await call(org_invoke)).text
        org_cp = BASE + "/connectors/" + org["id"] + "/connection"
        assert (
            await api.put(
                org_cp, headers=bearer(acatalog), json={"values": {"token": "ds-lab-alice"}}
            )
        ).status_code == 409
        assert (await api.delete(org_cp, headers=bearer(acatalog))).status_code == 409
        # Tokens scoped to another connector may not be substituted.
        crossed_service = {**org_invoke, "endpoint": ainvoke["endpoint"]}
        assert (await call(crossed_service)).status_code == 403
        assert (
            await api.post("/api/v1/desktop/logout", json={"refresh_token": broot["refresh_token"]})
        ).status_code == 200
        assert (await call(binvoke)).status_code == 401
