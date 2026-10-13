"""Real PostgreSQL device/permission/concurrency tests; separate live OIDC probe."""

import asyncio
import secrets
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from test_identity_access import env as identity_environment

from app.modules.auth.service import digest, now
from app.modules.desktop.models import DesktopLogin, DeviceSession, DeviceToken
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop.service import pkce
from app.modules.members.models import Membership
from app.modules.users.models import LoginIdentity, User

env = identity_environment
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


def native_client(env):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://test")


async def attempt(env, api, user, **overrides):
    env.provider.metadata = AsyncMock(
        return_value={"authorization_endpoint": env.provider.settings.oidc_issuer + "/auth"}
    )
    verifier = secrets.token_urlsafe(32)
    payload = {
        "contract_version": 1,
        "redirect_uri": "http://127.0.0.1:49161/actvero/callback",
        "code_challenge": pkce(verifier),
        "device_name": "测试电脑",
        "os": "macOS",
        "app_version": "0.1.0",
        **overrides,
    }
    response = await api.post("/api/v1/desktop/login/start", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    return (
        {
            "attempt_id": data["attempt_id"],
            "state": data["state"],
            "issuer": data["issuer"],
            "code_verifier": verifier,
            "code": "one-time-code",
        },
        payload,
        data,
    )


async def login(env, monkeypatch, api, user, auth_time=None, **overrides):
    claims = {
        "sub": user.identity.subject,
        "auth_time": auth_time if auth_time is not None else int(now().timestamp()),
        "name": user.user.name,
        "email": user.user.email,
    }
    monkeypatch.setattr(NativeIdentity, "exchange", AsyncMock(return_value=claims))
    proof, payload, data = await attempt(env, api, user, **overrides)
    response = await api.post("/api/v1/desktop/login/exchange", json=proof)
    assert response.status_code == 200, response.text
    return response.json(), proof


def bearer(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


async def test_same_identity_devices_independent_logout_web_and_bootstrap(env, monkeypatch):
    web = await env.client()
    async with native_client(env) as api:
        first, proof = await login(env, monkeypatch, api, web)
        second, _ = await login(env, monkeypatch, api, web, device_name="另一台电脑", os="Windows")
        me = (await api.get("/api/v1/desktop/me", headers=bearer(first))).json()
        assert me["user"]["id"] == str(web.user.id)
        assert me["organization"]["tenant_id"] == str(web.tenant.id)
        assert first["device_session_id"] != second["device_session_id"]
        bootstrap = await api.get(
            "/api/v1/desktop/bootstrap",
            params={"tenant_id": str(web.tenant.id)},
            headers=bearer(first),
        )
        assert bootstrap.status_code == 200
        assert {m["name"]: m["status"] for m in bootstrap.json()["modules"]} == {
            "models": "available",
            "mcp": "available",
            "skills": "available",
            "experts": "available",
        }
        assert all("endpoint" not in m for m in bootstrap.json()["modules"])
        listed = await web.api.get("/api/v1/account/devices")
        assert len(listed.json()["items"]) == 2
        assert "token" not in listed.text
        assert (
            await api.post("/api/v1/desktop/logout", json={"refresh_token": first["refresh_token"]})
        ).status_code == 200
        assert (
            await api.post("/api/v1/desktop/logout", json={"refresh_token": first["refresh_token"]})
        ).status_code == 200
        assert (await api.get("/api/v1/desktop/me", headers=bearer(first))).json()["error"][
            "code"
        ] == "device_revoked"
        assert (await api.post("/api/v1/desktop/login/exchange", json=proof)).status_code == 401
        assert (
            await api.post(
                "/api/v1/desktop/refresh",
                json={"refresh_token": first["refresh_token"], "request_id": str(uuid4())},
            )
        ).status_code == 401
        assert (await api.get("/api/v1/desktop/me", headers=bearer(second))).status_code == 200
        assert (await web.api.get(web.path + "/members")).status_code == 200


async def test_refresh_rotation_retry_races_and_restart(env, monkeypatch):
    web = await env.client()
    async with native_client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        body = {"refresh_token": tokens["refresh_token"], "request_id": str(uuid4())}
        responses = await asyncio.gather(
            *[api.post("/api/v1/desktop/refresh", json=body) for _ in range(3)]
        )
        assert all(r.status_code == 200 for r in responses)
        assert len({r.json()["refresh_token"] for r in responses}) == 1
        rotated = responses[0].json()
        assert rotated["refresh_token"] != tokens["refresh_token"]
        assert (
            await api.post("/api/v1/desktop/refresh", json={**body, "request_id": str(uuid4())})
        ).status_code == 409
        # Request with a new client/connection uses only durable database state.
        async with native_client(env) as restarted:
            replay = await restarted.post("/api/v1/desktop/refresh", json=body)
            assert replay.json()["refresh_token"] == rotated["refresh_token"]
        assert (await api.get("/api/v1/desktop/me", headers=bearer(tokens))).status_code == 200
        result = await asyncio.gather(
            api.post(
                "/api/v1/desktop/refresh",
                json={"refresh_token": rotated["refresh_token"], "request_id": str(uuid4())},
            ),
            api.post("/api/v1/desktop/logout", json={"refresh_token": tokens["refresh_token"]}),
        )
        assert result[1].status_code == 200
        for r in result:
            if r.status_code == 200 and "access_token" in r.json():
                assert (
                    await api.get("/api/v1/desktop/me", headers=bearer(r.json()))
                ).status_code == 401
        assert (await api.get("/api/v1/desktop/me", headers=bearer(rotated))).status_code == 401


async def test_login_proof_cancellation_replay_and_validation(env, monkeypatch):
    web = await env.client()
    async with native_client(env) as api:
        tokens, proof = await login(env, monkeypatch, api, web)
        repeat = await api.post("/api/v1/desktop/login/exchange", json=proof)
        assert repeat.json()["device_session_id"] == tokens["device_session_id"]
        for changes in (
            {"state": secrets.token_urlsafe(32)},
            {"code_verifier": secrets.token_urlsafe(32)},
            {"issuer": "https://other.example"},
        ):
            assert (
                await api.post("/api/v1/desktop/login/exchange", json={**proof, **changes})
            ).status_code == 401
        cancel = {k: proof[k] for k in ("attempt_id", "state", "code_verifier")}
        assert (await api.post("/api/v1/desktop/login/cancel", json=cancel)).status_code == 200
        assert (await api.get("/api/v1/desktop/me", headers=bearer(tokens))).status_code == 401
        assert (await api.post("/api/v1/desktop/login/exchange", json=proof)).json()["error"][
            "code"
        ] == "login_cancelled"
        _, payload, _ = await attempt(env, api, web)
        for uri in (
            "http://localhost:49161/actvero/callback",
            "https://evil.example/callback",
            "http://127.0.0.1:49161/wrong",
            "http://127.0.0.1:49161/actvero/callback?next=evil",
        ):
            assert (
                await api.post("/api/v1/desktop/login/start", json={**payload, "redirect_uri": uri})
            ).status_code == 422
        assert (
            await api.post("/api/v1/desktop/login/start", json={**payload, "contract_version": 2})
        ).json()["error"]["code"] == "unsupported_contract"


async def test_desktop_never_accepts_cookie_raw_oidc_or_confers_admin(env, monkeypatch):
    web = await env.client()
    async with native_client(env) as api:
        tokens, proof = await login(env, monkeypatch, api, web)
        for raw in ("id-token", "upstream-access-token", tokens["refresh_token"], str(uuid4())):
            response = await api.get(
                "/api/v1/desktop/me", headers={"Authorization": "Bearer " + raw}
            )
            assert response.status_code == 401
            assert response.json()["error"]["request_id"] == response.headers["X-Request-ID"]
        assert (await web.api.get("/api/v1/desktop/me", headers=bearer(tokens))).status_code == 401
        assert (await web.api.get(web.path + "/members", headers=bearer(tokens))).status_code == 401
        assert (await api.get(web.path + "/members", headers=bearer(tokens))).status_code == 401
        assert (
            await api.post(
                web.path + "/invitations",
                headers=bearer(tokens),
                json={"request_id": str(uuid4()), "email": "target@example.com", "name": "目标"},
            )
        ).status_code == 403
        assert (
            await api.post(
                "/api/v1/desktop/login/exchange", json={**proof, "device_id": str(uuid4())}
            )
        ).status_code == 422
        assert (
            await api.get(
                "/api/v1/desktop/bootstrap",
                params={"tenant_id": str(uuid4())},
                headers=bearer(tokens),
            )
        ).json()["error"]["code"] == "organization_denied"


async def test_membership_pause_restore_and_unknown_identity(env, monkeypatch):
    web = await env.client()
    async with native_client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        path = "/api/v1/desktop/bootstrap?tenant_id=" + str(web.tenant.id)
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.status = "paused"
            member.revoked_at = now()
            await db.commit()
        assert (await api.get(path, headers=bearer(tokens))).json()["error"][
            "code"
        ] == "member_suspended"
        assert (
            await api.post(
                "/api/v1/desktop/refresh",
                json={"refresh_token": tokens["refresh_token"], "request_id": str(uuid4())},
            )
        ).status_code == 200  # Identity recovery is independent of paused business membership.
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.status = "active"
            await db.commit()
        assert (await api.get(path, headers=bearer(tokens))).json()["error"][
            "code"
        ] == "reauthentication_required"
        restored, _ = await login(env, monkeypatch, api, web, auth_time=int(now().timestamp()) - 60)
        # Reusing old browser SSO auth_time must not bypass member recovery.
        assert (await api.get(path, headers=bearer(restored))).status_code == 401
        unknown = await env.client(joined=False, email=web.user.email)
        other, _ = await login(env, monkeypatch, api, unknown)
        me = (await api.get("/api/v1/desktop/me", headers=bearer(other))).json()
        assert me["organization"] is None
        assert me["user"]["id"] != str(web.user.id)
        assert (await api.get(path, headers=bearer(other))).status_code == 403


async def test_own_devices_web_csrf_and_revocation_idempotency(env, monkeypatch):
    one, other = await env.client(), await env.client()
    async with native_client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, one)
        foreign, _ = await login(env, monkeypatch, api, other)
        target = tokens["device_session_id"]
        own = await api.get("/api/v1/desktop/devices", headers=bearer(foreign))
        assert [d["id"] for d in own.json()["items"]] == [foreign["device_session_id"]]
        assert (
            await api.delete("/api/v1/desktop/devices/" + target, headers=bearer(foreign))
        ).status_code == 404
        assert (await other.api.delete("/api/v1/account/devices/" + target)).status_code == 404
        assert (
            await one.api.delete(
                "/api/v1/account/devices/" + target, headers={"x-csrf-token": "invalid"}
            )
        ).status_code == 403
        for _ in range(2):
            assert (await one.api.delete("/api/v1/account/devices/" + target)).status_code == 200
        assert (await api.get("/api/v1/desktop/me", headers=bearer(tokens))).status_code == 401


async def test_expiry_scope_and_upstream_failure_do_not_fake_logout(env, monkeypatch):
    web = await env.client()
    async with native_client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        monkeypatch.setattr(
            NativeIdentity, "account_valid", AsyncMock(side_effect=httpx.ConnectError("test"))
        )
        assert (await api.get("/api/v1/desktop/me", headers=bearer(tokens))).status_code == 503
        monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
        assert (await api.get("/api/v1/desktop/me", headers=bearer(tokens))).status_code == 200
        async with env.sessions() as db:
            token = await db.get(DeviceToken, digest(tokens["access_token"]))
            token.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await api.get("/api/v1/desktop/me", headers=bearer(tokens))).json()["error"][
            "code"
        ] == "access_expired"
        async with env.sessions() as db:
            session = await db.get(
                DeviceSession, __import__("uuid").UUID(tokens["device_session_id"])
            )
            session.scope = "admin"
            await db.commit()
        assert (await api.get("/api/v1/desktop/me", headers=bearer(tokens))).status_code == 403
        async with env.sessions() as db:
            session = await db.get(
                DeviceSession, __import__("uuid").UUID(tokens["device_session_id"])
            )
            session.scope = "desktop:self"
            session.idle_expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (
            await api.post(
                "/api/v1/desktop/refresh",
                json={"refresh_token": tokens["refresh_token"], "request_id": str(uuid4())},
            )
        ).json()["error"]["code"] == "session_expired"


async def test_concurrent_first_identity_mapping_and_login_exchange(env, monkeypatch):
    web = await env.client()
    subject = uuid4().hex
    monkeypatch.setattr(
        NativeIdentity,
        "exchange",
        AsyncMock(
            return_value={
                "sub": subject,
                "name": "新的成员",
                "email": web.user.email,
                "auth_time": int(now().timestamp()),
            }
        ),
    )
    async with native_client(env) as api:
        first, _, _ = await attempt(env, api, web)
        second, _, _ = await attempt(env, api, web)
        responses = await asyncio.gather(
            *[api.post("/api/v1/desktop/login/exchange", json=p) for p in (first, first, second)]
        )
        assert all(r.status_code == 200 for r in responses)
        assert len({r.json()["device_session_id"] for r in responses}) == 2
        async with env.sessions() as db:
            identities = (
                await db.scalars(select(LoginIdentity).where(LoginIdentity.subject == subject))
            ).all()
            assert len(identities) == 1
            assert identities[0].user_id != web.user.id
            assert len((await db.scalars(select(User))).all()) == 2


async def test_login_expired_and_cancel_during_exchange(env, monkeypatch):
    web = await env.client()
    async with native_client(env) as api:
        proof, _, _ = await attempt(env, api, web)
        async with env.sessions() as db:
            attempt_row = await db.get(DesktopLogin, __import__("uuid").UUID(proof["attempt_id"]))
            attempt_row.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await api.post("/api/v1/desktop/login/exchange", json=proof)).json()["error"][
            "code"
        ] == "login_expired"
        proof, _, _ = await attempt(env, api, web)
        started, proceed = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            started.set()
            await proceed.wait()
            return {"sub": web.identity.subject, "auth_time": int(now().timestamp())}

        monkeypatch.setattr(NativeIdentity, "exchange", delayed)
        task = asyncio.create_task(api.post("/api/v1/desktop/login/exchange", json=proof))
        await started.wait()
        cancel = asyncio.create_task(
            api.post(
                "/api/v1/desktop/login/cancel",
                json={k: proof[k] for k in ("attempt_id", "state", "code_verifier")},
            )
        )
        proceed.set()
        result, cancelled = await asyncio.gather(task, cancel)
        assert cancelled.status_code == 200
        assert (
            await api.get("/api/v1/desktop/me", headers=bearer(result.json()))
        ).status_code == 401


async def test_same_email_different_issuer_never_merges_identity(env):
    from app.modules.auth.identity import resolve_identity

    web = await env.client()
    async with env.sessions() as db:
        identity, user = await resolve_identity(
            db,
            "https://another-issuer.example/realms/test",
            {"sub": web.identity.subject, "email": web.user.email, "name": "独立身份"},
        )
        await db.commit()
        assert user.id != web.user.id
        assert identity.id != web.identity.id
        assert user.email == web.user.email


async def test_refresh_retry_window_absolute_expiry_and_client_boundary(env, monkeypatch):
    from uuid import UUID

    web = await env.client()
    async with native_client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        body = {"refresh_token": tokens["refresh_token"], "request_id": str(uuid4())}
        response = await api.post("/api/v1/desktop/refresh", json=body)
        assert response.status_code == 200
        current = response.json()
        async with env.sessions() as db:
            token = await db.get(DeviceToken, digest(tokens["refresh_token"]))
            token.response_until = now() - timedelta(seconds=1)
            await db.commit()
        assert (await api.post("/api/v1/desktop/refresh", json=body)).status_code == 409
        assert (await api.get("/api/v1/desktop/me", headers=bearer(current))).status_code == 200
        async with env.sessions() as db:
            session = await db.get(DeviceSession, UUID(tokens["device_session_id"]))
            session.client_id = "another-client"
            await db.commit()
        assert (await api.get("/api/v1/desktop/me", headers=bearer(current))).status_code == 403
        async with env.sessions() as db:
            session = await db.get(DeviceSession, UUID(tokens["device_session_id"]))
            session.client_id = env.provider.settings.desktop_client_id
            session.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await api.get("/api/v1/desktop/me", headers=bearer(current))).json()["error"][
            "code"
        ] == "session_expired"
