"""Optional real Keycloak + isolated PostgreSQL PKCE proof, no production identity."""

import asyncio
import json
import os
import secrets
import signal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from test_identity_access import env as identity_environment
from test_llm_channels import create as create_channel

from app.modules.desktop.service import pkce
from app.modules.users.models import LoginIdentity

env = identity_environment


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization_version", [1, 2])
async def test_real_management_oidc_pkce_read_refresh_and_logout(env, authorization_version):
    issuer = os.getenv("ACTVERO_TEST_MANAGEMENT_ISSUER")
    if not issuer:
        pytest.skip("explicit disposable Keycloak issuer required")
    assert issuer == "http://127.0.0.1:56611/realms/actvero-cli-test"
    web = await env.client()
    expected_channel = await create_channel(web)
    settings = env.provider.settings
    settings.management_enabled = True
    settings.oidc_issuer = issuer
    settings.provisioner_client_secret = SecretStr("cli-test-provisioner-only")
    async with env.sessions() as db:
        identity = await db.get(LoginIdentity, web.identity.id)
        identity.issuer, identity.subject = issuer, "b7cddc60-d398-4d49-9c26-3b5f1dbdf5cf"
        await db.commit()
    verifier = secrets.token_urlsafe(48)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as api:
        metadata = await api.get("/api/v1/management/metadata")
        assert metadata.json()["client_id"] == "actvero-cli"
        started = await api.post(
            "/api/v1/management/login/start",
            json={
                "contract_version": 1,
                "authorization_version": authorization_version,
                "redirect_uri": "http://127.0.0.1:49163/actvero/cli/callback",
                "code_challenge": pkce(verifier),
                "device_name": "CLI real identity test",
            },
        )
        assert started.status_code == 200, started.status_code
        attempt = started.json()
        browser_url = attempt["authorization_url"]
        if authorization_version == 2:
            consent = await web.api.post(
                "/api/v1/cli-authorization/decision",
                json={
                    "attempt_id": attempt["attempt_id"],
                    "state": attempt["state"],
                    "approve": True,
                    "org_ids": [str(web.tenant.id)],
                    "scope": "management:read management:write",
                },
            )
            assert consent.status_code == 200, consent.status_code
            browser_url = consent.json()["redirect_url"]
        process = await asyncio.create_subprocess_exec(
            "node",
            str(Path(__file__).resolve().parents[2] / "scripts/test-management-login.mjs"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(json.dumps({"authorization_url": browser_url}).encode()),
                timeout=45,
            )
        finally:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        assert process.returncode == 0, stderr.decode()
        browser_result = json.loads(stdout)
        assert browser_result["state"] == attempt["state"]
        assert browser_result["issuer"] == issuer
        proof = {
            "attempt_id": attempt["attempt_id"],
            "state": attempt["state"],
            "issuer": issuer,
            "code_verifier": verifier,
            "code": browser_result["code"],
        }
        wrong = await api.post(
            "/api/v1/management/login/exchange",
            json={**proof, "code_verifier": secrets.token_urlsafe(48)},
        )
        assert wrong.status_code == 401
        exchanged = await api.post("/api/v1/management/login/exchange", json=proof)
        assert exchanged.status_code == 200, exchanged.status_code
        tokens = exchanged.json()
        headers = {"Authorization": "Bearer " + tokens["access_token"]}
        assert tokens["scope"] == (
            "management:read management:write" if authorization_version == 2 else "management:read"
        )
        if authorization_version == 2:
            status = (await api.get("/api/v1/management/me", headers=headers)).json()
            assert status["authorized_org_ids"] == [str(web.tenant.id)]
        orgs = await api.get("/api/v1/management/organizations", headers=headers)
        assert orgs.status_code == 200, orgs.status_code
        assert orgs.json()["items"][0]["org_id"] == str(web.tenant.id)
        channels = await api.get(
            f"/api/v1/management/organizations/{web.tenant.id}/channels", headers=headers
        )
        assert channels.status_code == 200
        assert channels.json()["result"]["items"][0]["id"] == expected_channel["id"]
        rotated = await api.post(
            "/api/v1/management/refresh",
            json={
                "refresh_token": tokens["refresh_token"],
                "request_id": str(uuid4()),
                "recovery_version": 2,
            },
        )
        assert rotated.status_code == 200
        fresh = rotated.json()
        assert fresh["refresh_token"] != tokens["refresh_token"]
        assert (
            await api.post(
                "/api/v1/management/refresh/acknowledge",
                json={
                    "refresh_token": fresh["refresh_token"],
                    "request_id": fresh["refresh_request_id"],
                },
            )
        ).status_code == 200
        assert (
            await api.post(
                "/api/v1/management/logout", json={"refresh_token": fresh["refresh_token"]}
            )
        ).status_code == 200
        assert (await api.get("/api/v1/management/me", headers=headers)).status_code == 401
