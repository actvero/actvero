"""Real npm CLI calls against an isolated platform over loopback HTTP."""

import asyncio
import json
import os
import shutil
import socket
from pathlib import Path

import pytest
import uvicorn
from test_experts import content
from test_identity_access import env as identity_environment
from test_management_cli import client, login
from test_management_cli import identity as management_identity
from test_skills import package

env = identity_environment
identity = management_identity


@pytest.mark.skipif(
    not shutil.which("node")
    or not (Path(__file__).resolve().parents[2] / "cli/dist/commands.js").exists(),
    reason="Run make cli-check and install Node to exercise the CLI integration",
)
@pytest.mark.asyncio
async def test_real_node_resource_commands_over_http(env, monkeypatch, tmp_path):
    from unittest.mock import AsyncMock

    from app.modules.management import oauth
    from app.modules.mcp import credentials, operations

    monkeypatch.setattr(oauth, "resolve", AsyncMock())
    monkeypatch.setattr(operations, "resolve", AsyncMock())
    monkeypatch.setattr(
        credentials, "token_request", AsyncMock(return_value={"access_token": "fixture-upstream"})
    )
    web = await env.client()
    async with client(env) as api:
        _tokens, _ = await login(env, monkeypatch, api, web, "management:read management:write")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(env.app, lifespan="off", log_level="critical", access_log=False)
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        (tmp_path / "skill.zip").write_bytes(package())
        (tmp_path / "oauth.json").write_text(
            json.dumps(
                {
                    "name": "OAuth Fixture",
                    "transport": "http",
                    "url": "https://mcp.example.test/mcp",
                    "auth_mode": "oauth",
                    "oauth": {
                        "authorization_url": "https://oauth.example.test/authorize",
                        "token_url": "https://oauth.example.test/token",
                        "client_id": "fixture-client",
                        "scopes": "read",
                    },
                }
            )
        )
        (tmp_path / "mcp.json").write_text(
            json.dumps({"name": "Fixture MCP", "transport": "builtin"})
        )
        (tmp_path / "expert.json").write_text(json.dumps({"content": content()}))
        process = await asyncio.create_subprocess_exec(
            "node",
            str(Path(__file__).resolve().parents[2] / "cli/test/platform-integration.mjs"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "ACTVERO_CLI_HOME": str(tmp_path / "cli-config")},
        )
        payload = {
            "issuer": env.provider.settings.oidc_issuer,
            "server": f"http://127.0.0.1:{port}",
            "org": str(web.tenant.id),
            "zip": str(tmp_path / "skill.zip"),
            "mcp": str(tmp_path / "mcp.json"),
            "expert": str(tmp_path / "expert.json"),
            "oauth": str(tmp_path / "oauth.json"),
        }
        out, err = await asyncio.wait_for(process.communicate(json.dumps(payload).encode()), 30)
        assert process.returncode == 0, err.decode()
        result = json.loads(out)
        assert result["ok"]
        assert (await web.api.get("/api/v1/skills/" + result["skill"])).json()["default_version_id"]
        assert (
            len((await web.api.get("/api/v1/experts/" + result["expert"])).json()["releases"]) == 1
        )
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()
