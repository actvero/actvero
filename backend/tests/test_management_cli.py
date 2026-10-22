"""Independent management credentials and explicit multi-organization access."""

import asyncio
import secrets
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select, text
from test_identity_access import env as identity_environment
from test_llm_channels import create as create_channel

from app.modules.auth.models import WebSession
from app.modules.auth.service import now
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop.service import pkce
from app.modules.management.models import ManagementLogin, ManagementSession, ManagementToken
from app.modules.members.models import Membership
from app.modules.tenants.models import PlatformOperator, Tenant

env = identity_environment
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/management"


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


def client(env):
    env.provider.settings.management_enabled = True
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://test")


async def login(env, monkeypatch, api, web, scope="management:read"):
    env.provider.metadata = AsyncMock(
        return_value={"authorization_endpoint": env.provider.settings.oidc_issuer + "/auth"}
    )
    monkeypatch.setattr(
        NativeIdentity,
        "exchange",
        AsyncMock(
            return_value={
                "sub": web.identity.subject,
                "auth_time": int(now().timestamp()),
                "name": web.user.name,
                "email": web.user.email,
            }
        ),
    )
    verifier = secrets.token_urlsafe(32)
    result = await api.post(
        BASE + "/login/start",
        json={
            "contract_version": 1,
            "redirect_uri": "http://127.0.0.1:49161/actvero/cli/callback",
            "code_challenge": pkce(verifier),
            "device_name": "Test CLI",
            "scope": scope,
        },
    )
    assert result.status_code == 200, result.text
    attempt = result.json()
    assert "client_id=actvero-cli" in attempt["authorization_url"]
    proof = {
        "attempt_id": attempt["attempt_id"],
        "state": attempt["state"],
        "issuer": attempt["issuer"],
        "code_verifier": verifier,
        "code": "one-time-code",
    }
    response = await api.post(BASE + "/login/exchange", json=proof)
    assert response.status_code == 200, response.text
    return response.json(), proof


def bearer(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


async def test_disabled_until_explicitly_enabled(env):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as api:
        response = await api.get(BASE + "/metadata")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "management_disabled"


async def test_login_is_independent_from_web_and_desktop(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, proof = await login(env, monkeypatch, api, web)
        assert tokens["scope"] == "management:read"
        assert tokens["access_token"].startswith("avm_access_")
        assert (await api.get(BASE + "/me", headers=bearer(tokens))).json()["user"]["id"] == str(
            web.user.id
        )
        assert (await api.get("/api/v1/desktop/me", headers=bearer(tokens))).status_code == 401
        assert (await api.get("/api/v1/llm/channels", headers=bearer(tokens))).status_code == 401
        assert (await web.api.get(BASE + "/me", headers=bearer(tokens))).status_code == 401
        assert (
            await api.get(
                BASE + "/me", headers={**bearer(tokens), "Origin": env.provider.settings.app_url}
            )
        ).status_code == 401
        for raw in ("avd_access_test", "personal-key", "oidc-token"):
            assert (
                await api.get(BASE + "/me", headers={"Authorization": "Bearer " + raw})
            ).status_code == 401
        retry = await api.post(BASE + "/login/exchange", json=proof)
        assert retry.json()["refresh_token"] == tokens["refresh_token"]


async def test_explicit_two_org_queries_and_foreign_resource_hidden(env, monkeypatch):
    web = await env.client()
    first = await create_channel(web)
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        second = Tenant(name="Other authorized organization")
        db.add(second)
        await db.flush()
        db.add(
            Membership(
                tenant_id=second.id, user_id=web.user.id, role="administrator", source="invitation"
            )
        )
        await db.commit()
    other_admin = await env.client(tenant=second)
    async with env.sessions() as db:
        other_session = await db.get(WebSession, other_admin.session.id)
        other_session.tenant_id = second.id
        await db.commit()
    other = await create_channel(other_admin)
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        heads = bearer(tokens)
        orgs = (await api.get(BASE + "/organizations", headers=heads)).json()
        assert {r["org_id"] for r in orgs["items"]} == {str(web.tenant.id), str(second.id)}
        responses = await asyncio.gather(
            *[
                api.get(BASE + f"/organizations/{org}/channels", headers=heads)
                for org in (web.tenant.id, second.id)
            ]
        )
        assert responses[0].json()["result"]["items"][0]["id"] == first["id"]
        assert responses[1].json()["result"]["items"][0]["id"] == other["id"]
        assert responses[0].json()["organization"]["org_id"] == str(web.tenant.id)
        assert responses[1].json()["organization"]["org_id"] == str(second.id)
        assert "test-secret" not in responses[0].text + responses[1].text
        assert (
            await api.get(
                BASE + f"/organizations/{web.tenant.id}/channels/{other['id']}", headers=heads
            )
        ).status_code == 404
        assert (
            await api.get(BASE + f"/organizations/{uuid4()}/channels", headers=heads)
        ).status_code == 403
        assert (await api.get(BASE + "/channels", headers=heads)).status_code == 404


async def test_member_can_inspect_org_but_not_admin_resources(env, monkeypatch):
    web = await env.client(role="member")
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        root = BASE + f"/organizations/{web.tenant.id}"
        result = await api.get(root + "/permissions", headers=bearer(tokens))
        assert result.json()["permissions"] == ["org.show", "org.permissions"]
        assert (await api.get(root + "/channels", headers=bearer(tokens))).status_code == 403
        assert (
            await api.post(root + "/channels", json={}, headers=bearer(tokens))
        ).status_code == 405


async def test_live_role_pause_and_regrant_require_fresh_authentication(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        root = BASE + f"/organizations/{web.tenant.id}"
        assert (await api.get(root + "/channels", headers=bearer(tokens))).status_code == 200
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.role = "member"
            await db.commit()
        assert (await api.get(root + "/channels", headers=bearer(tokens))).status_code == 403
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.status = "paused"
            member.revoked_at = now()
            await db.commit()
        assert (await api.get(root, headers=bearer(tokens))).status_code == 403
        listed = (await api.get(BASE + "/organizations", headers=bearer(tokens))).json()["items"][0]
        assert not listed["available"] and not listed["permissions"]
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.status = "active"
            await db.commit()
        assert (await api.get(root, headers=bearer(tokens))).status_code == 401


async def test_platform_assignment_is_explicit_and_operator_revocation_is_live(env, monkeypatch):
    web = await env.client()
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        member = await db.get(Membership, web.member.id)
        member.source, member.role = "platform", "member"
        operator = PlatformOperator(user_id=web.user.id, status="active")
        db.add(operator)
        await db.commit()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        root = BASE + f"/organizations/{web.tenant.id}"
        assert (await api.get(root + "/permissions", headers=bearer(tokens))).json()[
            "authority"
        ] == "platform"
        assert (await api.get(root + "/channels", headers=bearer(tokens))).status_code == 200
        async with env.sessions() as db:
            row = await db.get(PlatformOperator, operator.user_id)
            row.status = "paused"
            await db.commit()
        assert (await api.get(root + "/channels", headers=bearer(tokens))).status_code == 403


async def test_refresh_parallel_retry_acknowledgement_and_revocation(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        body = {
            "refresh_token": tokens["refresh_token"],
            "request_id": str(uuid4()),
            "recovery_version": 2,
        }
        responses = await asyncio.gather(
            *[api.post(BASE + "/refresh", json=body) for _ in range(3)]
        )
        assert all(r.status_code == 200 for r in responses)
        assert len({r.json()["refresh_token"] for r in responses}) == 1
        next_tokens = responses[0].json()
        assert (
            await api.post(BASE + "/refresh", json={**body, "request_id": str(uuid4())})
        ).status_code == 409
        acknowledge = await api.post(
            BASE + "/refresh/acknowledge",
            json={"refresh_token": next_tokens["refresh_token"], "request_id": body["request_id"]},
        )
        assert acknowledge.status_code == 200
        assert (await api.post(BASE + "/refresh", json=body)).status_code == 409
        async with env.sessions() as db:
            cached = (
                await db.scalars(
                    select(ManagementToken).where(ManagementToken.used_at.is_not(None))
                )
            ).all()
            assert all(row.response is None for row in cached)
        for _ in range(2):
            assert (
                await api.post(BASE + "/logout", json={"refresh_token": tokens["refresh_token"]})
            ).status_code == 200
        assert (await api.get(BASE + "/me", headers=bearer(next_tokens))).status_code == 401
        assert (await web.api.get("/api/v1/llm/channels")).status_code == 200


async def test_access_expiry_refresh_idle_and_absolute_cap(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web)
        async with env.sessions() as db:
            access = await db.scalar(
                select(ManagementToken).where(ManagementToken.kind == "access")
            )
            access.expires_at = now() - timedelta(seconds=1)
            row = await db.get(ManagementSession, UUID(tokens["session_id"]))
            row.absolute_expires_at = now() + timedelta(hours=1)
            await db.commit()
        assert (await api.get(BASE + "/me", headers=bearer(tokens))).json()["error"][
            "code"
        ] == "access_expired"
        result = await api.post(
            BASE + "/refresh",
            json={"refresh_token": tokens["refresh_token"], "request_id": str(uuid4())},
        )
        assert result.status_code == 200
        assert result.json()["session_expires_at"] == result.json()["reauthenticate_at"]
        async with env.sessions() as db:
            row = await db.get(ManagementSession, UUID(tokens["session_id"]))
            row.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await api.get(BASE + "/me", headers=bearer(result.json()))).status_code == 401


async def test_cancel_after_exchange_revokes_only_that_cli_session(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        first, proof = await login(env, monkeypatch, api, web)
        second, _ = await login(env, monkeypatch, api, web)
        for changes in (
            {"state": secrets.token_urlsafe(32)},
            {"code_verifier": secrets.token_urlsafe(32)},
        ):
            assert (
                await api.post(BASE + "/login/exchange", json={**proof, **changes})
            ).status_code == 401
        body = {key: proof[key] for key in ("attempt_id", "state", "code_verifier")}
        assert (await api.post(BASE + "/login/cancel", json=body)).status_code == 200
        assert (await api.get(BASE + "/me", headers=bearer(first))).status_code == 401
        assert (await api.get(BASE + "/me", headers=bearer(second))).status_code == 200
        assert (await api.post(BASE + "/login/exchange", json=proof)).status_code == 401


@pytest.mark.parametrize(
    "uri",
    [
        "http://127.0.0.1:49161/actvero/callback",
        "http://localhost:49161/actvero/cli/callback",
        "https://evil.example/actvero/cli/callback",
        "http://127.0.0.1:49161/actvero/cli/callback?extra=1",
    ],
)
async def test_management_redirect_isolated_and_strict(env, uri):
    async with client(env) as api:
        response = await api.post(
            BASE + "/login/start",
            json={
                "contract_version": 1,
                "redirect_uri": uri,
                "code_challenge": pkce(secrets.token_urlsafe(32)),
                "device_name": "test",
            },
        )
        assert response.status_code == 422


async def test_uncertain_exchange_not_reused_as_new_login(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        _, proof = await login(env, monkeypatch, api, web)
        async with env.sessions() as db:
            row = await db.get(ManagementLogin, UUID(proof["attempt_id"]))
            row.consumed, row.response, row.session_id = False, None, None
            await db.commit()
        exchange = AsyncMock(side_effect=httpx.ConnectError("identity offline"))
        monkeypatch.setattr(NativeIdentity, "exchange", exchange)
        assert (await api.post(BASE + "/login/exchange", json=proof)).status_code == 503
        assert (await api.post(BASE + "/login/exchange", json=proof)).status_code == 409
        assert exchange.call_count == 1
