"""Optional artifact-based DS client interoperability; disposable schemas only.

Set DSH_CONNECTORS_PROBE to a built module's scripts/verify-platform.mjs.
Normal builds/tests have no sibling-project dependency. Login exchange is stubbed;
subsequent catalog, resource-token and MCP traffic uses real TCP and PostgreSQL.
"""

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from test_desktop import login, native_client
from test_identity_access import env as identity_environment
from test_mcp import create, listening, update
from test_mcp import upstream as protocol_fixture

from app.modules.desktop.oidc import NativeIdentity

env = identity_environment
upstream = protocol_fixture
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not os.getenv("DSH_CONNECTORS_PROBE"), reason="Explicit built DS module required"
    ),
]


async def test_ds_client_all_capabilities_and_revocation(env, upstream, monkeypatch):
    probe = Path(os.environ["DSH_CONNECTORS_PROBE"]).resolve(strict=True)
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, member = await env.client(), await env.client(role="member")
    row = await create(admin, transport=transport, url=url)
    path = "/api/v1/mcp/services/" + row["id"]
    assert (await admin.api.post(path + "/discover")).status_code == 200
    row = await update(admin, row, enabled=True)
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, member)
    # The fixture already owns app lifespan; mounting avoids starting it twice.
    wrapper = FastAPI()
    wrapper.mount("/", env.app)
    async with listening(wrapper) as address:
        env.provider.settings.app_url = address
        admin.api.headers["origin"] = address
        process = await asyncio.create_subprocess_exec(
            "node",
            str(probe),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            process.stdin.write(
                json.dumps(
                    {"base": address, "id": row["id"], "access": root["access_token"]}
                ).encode()
                + b"\n"
            )
            await process.stdin.drain()
            assert await asyncio.wait_for(process.stdout.readline(), 30) == b"CAPABILITIES_OK\n"
            assert (
                await admin.api.put(
                    path + "/policy", json={"kind": "tools", "key": "add", "enabled": False}
                )
            ).status_code == 200
            process.stdin.write(b"continue\n")
            await process.stdin.drain()
            assert await asyncio.wait_for(process.stdout.readline(), 30) == b"POLICY_REVOKE_OK\n"
            await update(admin, row, enabled=False)
            process.stdin.write(b"continue\n")
            await process.stdin.drain()
            assert await asyncio.wait_for(process.stdout.readline(), 30) == b"SERVICE_REVOKE_OK\n"
            assert await asyncio.wait_for(process.wait(), 10) == 0
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
