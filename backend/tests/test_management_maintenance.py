"""CLI maintenance parity, replay privacy and OAuth/session isolation on isolated PostgreSQL."""

import asyncio
import hashlib
from datetime import timedelta
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from test_experts import content
from test_identity_access import env as identity_environment
from test_management_cli import bearer, client, identity, login  # noqa: F401
from test_management_resources import WRITE, headers
from test_mcp import create
from test_mcp import upstream as protocol_fixture
from test_skills import package, payload

from app.modules.auth.service import now
from app.modules.management.models import (
    ManagementCommand,
    ManagementOAuthAttempt,
    ManagementSession,
)
from app.modules.mcp import credentials
from app.modules.mcp.models import McpConnection, McpService
from app.modules.members.models import Membership
from app.modules.skills.models import SkillDistribution

env = identity_environment
upstream = protocol_fixture
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("kind", ["skills", "experts"])
async def test_categories_share_web_state_and_reject_stale_count(env, monkeypatch, kind):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}/{kind}"
        response = await api.post(
            root + "/categories", json={"name": "CLI category"}, headers=headers(tokens)
        )
        assert response.status_code == 200, response.text
        category = next(c for c in response.json()["result"] if c["name"] == "CLI category")
        path = root + "/categories/" + category["id"]
        resource = await api.post(
            root + ("/import" if kind == "skills" else ""),
            json=payload(category=category["id"])
            if kind == "skills"
            else {"content": content(), "category": category["id"]},
            headers=headers(tokens),
        )
        assert resource.status_code == 200, resource.text
        saved = resource.json()["result"]
        response = await api.request(
            "DELETE",
            path,
            json={"revision": category["revision"], "count": 0, "target_id": "uncategorized"},
            headers=headers(tokens),
        )
        assert response.status_code == 409
        renamed = await api.patch(
            path,
            json={"revision": category["revision"], "name": "Renamed"},
            headers=headers(tokens),
        )
        assert renamed.status_code == 200, renamed.text
        latest = next(c for c in renamed.json()["result"] if c["id"] == category["id"])
        assert latest["count"] == 1
        stale = await api.patch(
            path, json={"revision": category["revision"], "name": "Stale"}, headers=headers(tokens)
        )
        assert stale.status_code == 409
        moved = await api.post(
            path + "/move",
            json={"revision": latest["revision"], "direction": "up"},
            headers=headers(tokens),
        )
        assert moved.status_code == 200, moved.text
        latest = next(c for c in moved.json()["result"] if c["id"] == category["id"])
        deleted = await api.request(
            "DELETE",
            path,
            json={"revision": latest["revision"], "count": 1, "target_id": "uncategorized"},
            headers=headers(tokens),
        )
        assert deleted.status_code == 200, deleted.text
        detail = (await api.get(root + "/" + saved["id"], headers=bearer(tokens))).json()["result"]
        assert (
            detail["category"] if kind == "skills" else detail["category"]["id"]
        ) == "uncategorized"
        assert (await web.api.get(f"/api/v1/{kind}/" + saved["id"])).json() == detail
        readonly, _ = await login(env, monkeypatch, api, web)
        assert (
            await api.post(
                root + "/categories", json={"name": "No write"}, headers=headers(readonly)
            )
        ).status_code == 403
        assert (await api.get(root + "/categories", headers=bearer(readonly))).status_code == 200


async def test_download_replay_has_exact_bytes_one_audit_and_live_authority(env, monkeypatch):
    web = await env.client()
    data = package()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        skill = (
            await api.post(root + "/skills/import", json=payload(data), headers=headers(tokens))
        ).json()["result"]
        version = skill["versions"][0]["id"]
        path = root + f"/skills/{skill['id']}/versions/{version}/download"
        request_id = uuid4()
        for _ in range(2):
            response = await api.post(path, headers=headers(tokens, request_id))
            assert response.status_code == 200, response.text
            assert response.content == data
            assert response.headers["X-Content-SHA256"] == hashlib.sha256(data).hexdigest()
            assert response.headers["X-Organization-ID"] == str(web.tenant.id)
        async with env.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(SkillDistribution)) == 1
            receipt = await db.get(ManagementCommand, (web.tenant.id, web.user.id, request_id))
            assert set(receipt.result["result"]) == {
                "skill_id",
                "version_id",
                "filename",
                "sha256",
                "size",
            }
            await db.execute(
                update(Membership).where(Membership.id == web.member.id).values(role="member")
            )
            await db.commit()
        assert (await api.post(path, headers=headers(tokens, request_id))).status_code == 403


async def test_content_and_run_receipts_never_store_input_or_results(env, monkeypatch):
    web = await env.client()
    connector = await create(web)
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}/mcp"
        body = {
            "service_id": connector["id"],
            "kind": "prompts",
            "name": "hello",
            "body": "Hello {{name}}",
            "arguments": ["name"],
        }
        response = await api.post(root + "/contents", json=body, headers=headers(tokens))
        assert response.status_code == 200, response.text
        content_id = response.json()["result"]["id"]
        assert (await api.get(root + "/contents", headers=bearer(tokens))).json()["result"][
            "items"
        ][0]["id"] == content_id
        request_id = uuid4()
        args = {"kind": "prompts", "key": "hello", "arguments": {"name": "PRIVATE-INPUT"}}
        path = root + "/services/" + connector["id"] + "/run"
        response = await api.post(path, json=args, headers=headers(tokens, request_id))
        assert response.status_code == 200, response.text
        assert "Hello PRIVATE-INPUT" in response.text
        replay = await api.post(path, json=args, headers=headers(tokens, request_id))
        assert replay.status_code == 409
        assert replay.json()["error"]["code"] == "command_result_not_retained"
        async with env.sessions() as db:
            receipt = await db.get(ManagementCommand, (web.tenant.id, web.user.id, request_id))
            assert receipt.result["result"] == {"result_retained": False}
            assert "PRIVATE" not in str(receipt.result)
        activity = await api.get(root + "/activities?category=call", headers=bearer(tokens))
        assert activity.status_code == 200, activity.text
        assert "PRIVATE" not in activity.text
        assert activity.json()["result"]["total"] == 1
        assert activity.json()["result"]["items"][0]["source"] == "management"
        assert (
            await api.put(
                root + "/contents/" + content_id,
                json={**body, "body": "Changed"},
                headers=headers(tokens),
            )
        ).status_code == 200
        assert (
            await api.delete(root + "/contents/" + content_id, headers=headers(tokens))
        ).status_code == 200


async def test_real_mcp_http_sse_run_replay_and_revocation_before_dispatch(
    env, monkeypatch, upstream
):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    web = await env.client()
    connector = await create(web, transport=transport, url=url)
    from app.modules.mcp import service as mcp

    original_discover = mcp.discover
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        path = root + "/mcp/services/" + connector["id"]
        response = await api.post(path + "/discover", headers=headers(tokens))
        assert response.status_code == 200, response.text
        request_id = uuid4()
        args = {"kind": "tools", "key": "add", "arguments": {"a": 2, "b": 3}}
        response = await api.post(path + "/run", json=args, headers=headers(tokens, request_id))
        assert response.status_code == 200, response.text
        assert response.json()["result"]["result"]["content"][0]["text"] == "5"
        assert (
            await api.post(path + "/run", json=args, headers=headers(tokens, request_id))
        ).status_code == 409

        async def revoke_during_directory(mcp_client):
            directory = await original_discover(mcp_client)
            async with env.sessions() as db:
                await db.execute(
                    update(Membership).where(Membership.id == web.member.id).values(role="member")
                )
                await db.commit()
            return directory

        monkeypatch.setattr(mcp, "discover", revoke_during_directory)
        response = await asyncio.wait_for(
            api.post(path + "/run", json=args, headers=headers(tokens)), 10
        )
        assert response.status_code == 403, response.text
        assert "content" not in response.json().get("result", {})


async def oauth_setup(env, monkeypatch, api, web):
    from app.modules.management import oauth

    monkeypatch.setattr(oauth, "resolve", AsyncMock())
    connector = await create(web)
    async with env.sessions() as db:
        row = await db.get(McpService, UUID(connector["id"]))
        row.auth_mode = "oauth"
        row.oauth = {
            "authorization_url": "https://oauth.example.test/authorize",
            "token_url": "https://oauth.example.test/token",
            "client_id": "cli-fixture",
            "scopes": "read",
        }
        await db.commit()
    tokens, _ = await login(env, monkeypatch, api, web, WRITE)
    root = f"/api/v1/management/organizations/{web.tenant.id}/mcp"
    request_id = uuid4()
    response = await api.post(
        root + "/services/" + connector["id"] + "/oauth/start", headers=headers(tokens, request_id)
    )
    assert response.status_code == 200, response.text
    attempt = response.json()["result"]
    assert attempt["id"] == str(request_id)
    state = parse_qs(urlsplit(attempt["authorization_url"]).query)["state"][0]
    return tokens, root, connector["id"], attempt, state


async def test_oauth_stages_secrets_and_only_initiating_cli_can_attach(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, root, service_id, attempt, state = await oauth_setup(env, monkeypatch, api, web)
        exchange = AsyncMock(
            return_value={"access_token": "SECRET-UPSTREAM", "refresh_token": "SECRET-REFRESH"}
        )
        monkeypatch.setattr(credentials, "token_request", exchange)
        aid = attempt["id"]
        other, _ = await login(env, monkeypatch, api, web, WRITE)
        assert (await api.get(root + "/oauth/" + aid, headers=bearer(other))).status_code == 404
        assert (
            await api.post(root + "/oauth/" + aid + "/complete", headers=headers(other))
        ).status_code == 404
        resumed = await api.get(root + "/oauth/" + aid, headers=bearer(tokens))
        assert resumed.json()["result"]["authorization_url"] == attempt["authorization_url"]
        callback = "/api/v1/management/mcp/oauth/callback"
        assert (
            await api.get(callback, params=[("state", state), ("state", state), ("code", "code")])
        ).status_code == 400
        response = await web.api.get(callback, params={"state": state, "code": "one-use-code"})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        async with env.sessions() as db:
            assert await db.get(McpConnection, (UUID(service_id), web.member.id)) is None
            saved = await db.get(ManagementOAuthAttempt, UUID(aid))
            assert saved.verifier is None and saved.authorization_url is None
            assert "SECRET" not in saved.pending_tokens
            receipt = await db.get(ManagementCommand, (web.tenant.id, web.user.id, UUID(aid)))
            assert receipt.result["result"] == {"result_retained": False}
        proof = exchange.call_args.args[2]
        from app.modules.desktop.service import pkce

        assert (
            pkce(proof["code_verifier"])
            == parse_qs(urlsplit(attempt["authorization_url"]).query)["code_challenge"][0]
        )
        assert (
            await api.get(callback, params={"state": state, "code": "replay"})
        ).status_code == 400
        assert exchange.await_count == 1
        request_id = uuid4()
        for _ in range(2):
            response = await api.post(
                root + "/oauth/" + aid + "/complete", headers=headers(tokens, request_id)
            )
            assert response.status_code == 200, response.text
            assert response.json()["result"]["status"] == "completed"
            assert "SECRET" not in response.text
        async with env.sessions() as db:
            connection = await db.get(McpConnection, (UUID(service_id), web.member.id))
            assert env.provider.unseal(connection.sealed)["access_token"] == "SECRET-UPSTREAM"
            assert (await db.get(ManagementOAuthAttempt, UUID(aid))).pending_tokens is None


@pytest.mark.parametrize("change", ["cancel", "disconnect", "expired", "version", "role", "logout"])
async def test_oauth_cannot_attach_after_invalidation(env, monkeypatch, change):
    web = await env.client()
    async with client(env) as api:
        tokens, root, service_id, attempt, state = await oauth_setup(env, monkeypatch, api, web)
        aid = attempt["id"]
        monkeypatch.setattr(
            credentials, "token_request", AsyncMock(return_value={"access_token": "SECRET"})
        )
        response = await api.get(
            "/api/v1/management/mcp/oauth/callback", params={"state": state, "code": "code"}
        )
        assert response.status_code == 200
        if change == "cancel":
            assert (
                await api.post(root + "/oauth/" + aid + "/cancel", headers=headers(tokens))
            ).status_code == 200
        elif change == "disconnect":
            assert (
                await web.api.delete("/api/v1/mcp/services/" + service_id + "/connection")
            ).status_code == 200
        else:
            async with env.sessions() as db:
                if change == "expired":
                    (await db.get(ManagementOAuthAttempt, UUID(aid))).expires_at = (
                        now() - timedelta(seconds=1)
                    )
                elif change == "version":
                    (await db.get(McpService, UUID(service_id))).version += 1
                elif change == "role":
                    (await db.get(Membership, web.member.id)).role = "member"
                else:
                    (await db.get(ManagementSession, UUID(tokens["session_id"]))).revoked_at = now()
                await db.commit()
        response = await api.post(root + "/oauth/" + aid + "/complete", headers=headers(tokens))
        assert response.status_code in {200, 401, 403}, response.text
        if response.status_code == 200:
            assert response.json()["result"]["status"] in {"cancelled", "expired", "failed"}
        async with env.sessions() as db:
            assert await db.get(McpConnection, (UUID(service_id), web.member.id)) is None


async def test_oauth_cancel_during_exchange_never_attaches_or_retains_tokens(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, root, service_id, attempt, state = await oauth_setup(env, monkeypatch, api, web)
        entered, release = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            entered.set()
            await release.wait()
            return {"access_token": "SECRET"}

        monkeypatch.setattr(credentials, "token_request", delayed)
        task = asyncio.create_task(
            api.get(
                "/api/v1/management/mcp/oauth/callback", params={"state": state, "code": "code"}
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            response = await asyncio.wait_for(
                api.post(root + "/oauth/" + attempt["id"] + "/cancel", headers=headers(tokens)), 5
            )
            assert response.status_code == 200, response.text
        finally:
            release.set()
            await task
        async with env.sessions() as db:
            saved = await db.get(ManagementOAuthAttempt, UUID(attempt["id"]))
            assert saved.status == "cancelled" and saved.pending_tokens is None
            assert await db.get(McpConnection, (UUID(service_id), web.member.id)) is None


async def test_oauth_uses_real_bounded_http_token_exchange(env, monkeypatch):
    from fastapi import FastAPI, Request
    from test_mcp import listening

    from app.modules.desktop.service import pkce

    upstream_app = FastAPI()
    calls = []

    @upstream_app.post("/token")
    async def exchange(request: Request):
        calls.append(dict(await request.form()))
        return {
            "access_token": "loopback-access",
            "refresh_token": "loopback-refresh",
            "token_type": "Bearer",
            "expires_in": 300,
        }

    async with listening(upstream_app) as base:
        env.provider.settings.mcp_allowed_private_origins = [base]
        web = await env.client()
        connector = await create(
            web,
            transport="http",
            url=base + "/mcp",
            auth_mode="oauth",
            oauth={
                "authorization_url": base + "/authorize",
                "token_url": base + "/token",
                "client_id": "fixture-client",
                "scopes": "read",
            },
        )
        async with client(env) as api:
            tokens, _ = await login(env, monkeypatch, api, web, WRITE)
            root = f"/api/v1/management/organizations/{web.tenant.id}/mcp"
            response = await api.post(
                root + "/services/" + connector["id"] + "/oauth/start", headers=headers(tokens)
            )
            assert response.status_code == 200, response.text
            attempt = response.json()["result"]
            query = parse_qs(urlsplit(attempt["authorization_url"]).query)
            callback = await api.get(
                "/api/v1/management/mcp/oauth/callback",
                params={"state": query["state"][0], "code": "one-time-code"},
            )
            assert callback.status_code == 200, callback.text
            assert len(calls) == 1
            assert calls[0]["code"] == "one-time-code"
            assert pkce(calls[0]["code_verifier"]) == query["code_challenge"][0]
            assert calls[0]["redirect_uri"] == query["redirect_uri"][0]
            completed = await api.post(
                root + "/oauth/" + attempt["id"] + "/complete", headers=headers(tokens)
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["result"]["status"] == "completed"
            async with env.sessions() as db:
                row = await db.get(McpConnection, (UUID(connector["id"]), web.member.id))
                assert env.provider.unseal(row.sealed)["access_token"] == "loopback-access"
