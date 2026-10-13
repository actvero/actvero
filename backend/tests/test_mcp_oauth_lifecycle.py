"""Real Authlib, isolated PostgreSQL and loopback OAuth; no external credentials."""

import asyncio
import time

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from test_identity_access import env as env
from test_mcp import listening

from app.modules.desktop_mcp.service import connection_state
from app.modules.mcp import credentials
from app.modules.mcp.models import McpConnection, McpService
from app.modules.mcp.oauth_refresh import STATE, _pending

pytestmark = pytest.mark.asyncio


def request(env):
    return Request({"type": "http", "app": env.app})


async def seeded(env, base, actor):
    env.provider.settings.mcp_allowed_private_origins = [base]
    async with env.sessions() as db:
        row = McpService(
            tenant_id=actor.tenant.id,
            name="OAuth fixture",
            enabled=True,
            transport="http",
            url=base + "/mcp",
            auth_mode="oauth",
            oauth={"token_url": base + "/token", "client_id": "test"},
        )
        db.add(row)
        await db.flush()
        await credentials.store(
            request(env),
            db,
            row,
            actor,
            {"access_token": "old-access", "refresh_token": "one-use-refresh", "expires_at": 0},
        )
        await db.commit()
        return row


async def headers(env, service, actor):
    async with env.sessions() as db:
        result = await credentials.headers_for_owner(request(env), db, service, actor.member.id)
        await db.rollback()  # A later business failure must not roll back rotation.
        return result[0]


async def stored(env, service, actor):
    async with env.sessions() as db:
        row = await db.get(McpConnection, (service.id, actor.member.id))
        return env.provider.unseal(row.sealed)


async def test_two_workers_rotate_once_and_survive_outer_rollback(env):
    app = FastAPI()
    calls = []

    @app.post("/token")
    async def token(r: Request):
        data = dict(await r.form())
        calls.append(data)
        assert data == {
            "grant_type": "refresh_token",
            "refresh_token": "one-use-refresh",
            "client_id": "test",
        }
        await asyncio.sleep(0.05)
        return {
            "access_token": "new-access",
            "refresh_token": "next-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    async with listening(app) as base:
        actor = await env.client()
        service = await seeded(env, base, actor)
        results = await asyncio.gather(headers(env, service, actor), headers(env, service, actor))
        assert results == [{"Authorization": "Bearer new-access"}] * 2
        assert len(calls) == 1
        assert (await stored(env, service, actor))["refresh_token"] == "next-refresh"


async def test_cancelled_waiter_still_persists_known_rotation(env):
    app = FastAPI()
    entered, release = asyncio.Event(), asyncio.Event()

    @app.post("/token")
    async def token(r: Request):
        await r.form()
        entered.set()
        await release.wait()
        return {"access_token": "new-access", "refresh_token": "next-refresh", "expires_in": 3600}

    async with listening(app) as base:
        actor = await env.client()
        service = await seeded(env, base, actor)
        waiting = asyncio.create_task(headers(env, service, actor))
        await asyncio.wait_for(entered.wait(), 3)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        release.set()
        await asyncio.wait_for(asyncio.gather(*list(_pending)), 3)
        assert (await stored(env, service, actor))["refresh_token"] == "next-refresh"


@pytest.mark.parametrize(
    "status,error",
    [(429, "rate_limit"), (503, "invalid_grant"), (400, "invalid_client"), (200, "invalid_token")],
)
async def test_temporary_error_preserves_secrets_and_waits(env, status, error):
    app, calls = FastAPI(), []

    @app.post("/token")
    async def token(r: Request):
        calls.append(dict(await r.form()))
        return JSONResponse(
            {"error": error, "error_description": "private-upstream-value"},
            status_code=status,
            headers={"Retry-After": "90"},
        )

    async with listening(app) as base:
        actor = await env.client()
        service = await seeded(env, base, actor)
        for _ in range(2):
            with pytest.raises(HTTPException) as failure:
                await headers(env, service, actor)
            assert failure.value.status_code == 503
            assert "private" not in str(failure.value.detail)
        assert len(calls) == 1
        values = await stored(env, service, actor)
        assert (
            values["access_token"] == "old-access" and values["refresh_token"] == "one-use-refresh"
        )
        assert not values[STATE].get("reauthorization_required")
        if status in (429, 503):
            assert float(values[STATE]["retry_at"]) >= time.time() + 80
        async with env.sessions() as db:
            state = await connection_state(request(env), db, service, actor)
            assert state.status == "error" and state.action == "retry" and state.retry_after > 0


async def test_only_invalid_grant_requires_authorization_and_reconnect_clears_state(env):
    app, calls = FastAPI(), []
    invalid = True

    @app.post("/token")
    async def token(r: Request):
        calls.append(dict(await r.form()))
        if invalid:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "private-refresh"}, status_code=400
            )
        return {"access_token": "new-access", "expires_in": 3600}

    async with listening(app) as base:
        actor = await env.client()
        service = await seeded(env, base, actor)
        for _ in range(2):
            with pytest.raises(HTTPException) as failure:
                await headers(env, service, actor)
            assert failure.value.status_code == 409
        assert len(calls) == 1
        async with env.sessions() as db:
            assert (
                await connection_state(request(env), db, service, actor)
            ).status == "reauthorization_required"
            await credentials.store(
                request(env),
                db,
                service,
                actor,
                {
                    "access_token": "replacement",
                    "refresh_token": "replacement-refresh",
                    "expires_at": 0,
                },
            )
            await db.commit()
        invalid = False
        assert (await headers(env, service, actor))["Authorization"] == "Bearer new-access"
        assert (await stored(env, service, actor))["refresh_token"] == "replacement-refresh"
        assert STATE not in await stored(env, service, actor)


async def test_connection_owner_isolation_configuration_change_and_live_member_revocation(env):
    from app.modules.members.models import Membership

    app, calls = FastAPI(), []

    @app.post("/token")
    async def token(r: Request):
        calls.append(dict(await r.form()))
        return {"access_token": "new-access", "expires_in": 3600}

    async with listening(app) as base:
        actor, other = await env.client(), await env.client(role="member")
        service = await seeded(env, base, actor)
        with pytest.raises(HTTPException):
            await headers(env, service, other)
        assert not calls
        async with env.sessions() as db:
            member = await db.get(Membership, actor.member.id)
            member.status = "paused"
            await db.commit()
        with pytest.raises(HTTPException) as denied:
            await headers(env, service, actor)
        assert denied.value.status_code == 403 and not calls
        async with env.sessions() as db:
            member = await db.get(Membership, actor.member.id)
            member.status = "active"
            row = await db.get(McpService, service.id)
            row.version += 1
            await db.commit()
        with pytest.raises(HTTPException) as changed:
            await headers(env, service, actor)
        assert changed.value.status_code == 409 and not calls
        assert (await stored(env, service, actor))["refresh_token"] == "one-use-refresh"


@pytest.mark.parametrize(
    "shape", ["huge", "json", "header", "refresh", "type", "expiry", "redirect", "array"]
)
async def test_invalid_or_redirected_token_responses_are_bounded_and_preserved(env, shape):
    from fastapi.responses import PlainTextResponse, RedirectResponse

    app, redirected = FastAPI(), []

    @app.post("/token")
    async def token(r: Request):
        await r.form()
        if shape == "huge":
            return {"access_token": "valid", "extra": "x" * 70000}
        if shape == "json":
            return PlainTextResponse("not JSON")
        if shape == "array":
            return JSONResponse(["not", "a", "token"])
        if shape == "redirect":
            return RedirectResponse("/other", status_code=307)
        values = {"access_token": "valid-access", "token_type": "Bearer", "expires_in": 3600}
        values.update(
            {
                "header": {"access_token": "bad\nheader"},
                "refresh": {"refresh_token": ""},
                "type": {"token_type": "MAC"},
                "expiry": {"expires_in": "nan"},
            }.get(shape, {})
        )
        return values

    @app.post("/other")
    async def other():
        redirected.append(True)
        return {"access_token": "redirect-access"}

    async with listening(app) as base:
        actor = await env.client()
        service = await seeded(env, base, actor)
        with pytest.raises(HTTPException) as failure:
            await headers(env, service, actor)
        assert failure.value.status_code == 503 and not redirected
        assert (await stored(env, service, actor))["refresh_token"] == "one-use-refresh"


async def test_native_rpc_and_verification_preserve_temporary_wait(env, monkeypatch):
    from unittest.mock import AsyncMock

    from test_desktop import bearer, native_client
    from test_desktop_mcp import native, token

    from app.modules.desktop.oidc import NativeIdentity

    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    app = FastAPI()
    calls = 0

    @app.post("/token")
    async def limited():
        nonlocal calls
        calls += 1
        return JSONResponse(
            {"error": "invalid_grant"}, status_code=503, headers={"Retry-After": "7200"}
        )

    async with listening(app) as base:
        actor = await env.client(role="member")
        service = await seeded(env, base, actor)
        async with native_client(env) as api:
            root, catalog = await native(env, monkeypatch, api, actor)
            invocation = await token(api, root, "mcp:" + str(service.id))
            result = await api.post(
                invocation["endpoint"],
                headers={**bearer(invocation), "accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert result.status_code == 200
            data = result.json()["error"]["data"]
            assert data["code"] == "authorization_unavailable" and data["retry_after"] == 7200
            path = "/api/v1/desktop/mcp/connectors/" + str(service.id) + "/connection"
            verification = await api.post(path + "/verify", headers=bearer(catalog))
            assert verification.status_code == 503
            assert int(verification.headers["retry-after"]) >= 7199
            assert verification.json()["error"]["code"] == "authorization_unavailable"
            state = (await api.get(path, headers=bearer(catalog))).json()
            assert state["status"] == "error" and state["retry_after"] >= 7199
            assert (
                calls == 1
                and (await stored(env, service, actor))["refresh_token"] == "one-use-refresh"
            )
