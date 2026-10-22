"""CLI scopes and organizations require browser approval bound to the PKCE login."""

import secrets
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from test_experts import content
from test_identity_access import env as identity_environment
from test_management_cli import BASE, bearer, client, identity  # noqa: F401

from app.modules.auth.service import now
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop.service import pkce
from app.modules.management.models import ManagementLogin, ManagementSession
from app.modules.members.models import Membership
from app.modules.tenants.models import PlatformOperator, Tenant

env = identity_environment
pytestmark = pytest.mark.asyncio
WEB = "/api/v1/cli-authorization"
READ = "management:read"
WRITE = READ + " management:write"


async def start(env, api, monkeypatch, web):
    env.provider.metadata = AsyncMock(
        return_value={
            "authorization_endpoint": env.provider.settings.oidc_issuer + "/auth",
        }
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
    response = await api.post(
        BASE + "/login/start",
        json={
            "contract_version": 1,
            "authorization_version": 2,
            "scope": WRITE,
            "redirect_uri": "http://127.0.0.1:49161/actvero/cli/callback",
            "code_challenge": pkce(verifier),
            "device_name": "My terminal",
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["authorization_url"].startswith(env.provider.settings.app_url + "/cli/authorize#")
    proof = {"attempt_id": result["attempt_id"], "state": result["state"]}
    exchange = {**proof, "code_verifier": verifier, "issuer": result["issuer"], "code": "one-time"}
    return proof, exchange


async def approve(web, proof, scope=READ, ids=None):
    return await web.api.post(
        WEB + "/decision",
        json={
            **proof,
            "approve": True,
            "scope": scope,
            "org_ids": ids if ids is not None else [str(web.tenant.id)],
        },
    )


async def test_scope_parameter_cannot_replace_consent_and_browser_controls_grant(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        proof, exchange = await start(env, api, monkeypatch, web)
        denied = await api.post(BASE + "/login/exchange", json=exchange)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "consent_required"
        context = await web.api.post(WEB + "/context", json=proof)
        assert context.status_code == 200
        assert context.json()["device_name"] == "My terminal"
        assert len(context.json()["organizations"]) == 1
        response = await approve(web, proof, READ)
        assert response.status_code == 200, response.text
        assert "client_id=actvero-cli" in response.json()["redirect_url"]
        assert (await approve(web, proof, WRITE)).status_code == 409
        result = await api.post(BASE + "/login/exchange", json=exchange)
        assert result.status_code == 200, result.text
        assert result.json()["scope"] == READ
        me = (await api.get(BASE + "/me", headers=bearer(result.json()))).json()
        assert me["authorized_org_ids"] == [str(web.tenant.id)]
        permissions = await api.get(
            BASE + f"/organizations/{web.tenant.id}/permissions", headers=bearer(result.json())
        )
        assert "skills.write" not in permissions.json()["permissions"]


async def test_selected_organization_is_enforced_on_listing_read_write_and_refresh(
    env, monkeypatch
):
    web = await env.client()
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        other = Tenant(name="Other")
        db.add(other)
        await db.flush()
        db.add(
            Membership(
                tenant_id=other.id, user_id=web.user.id, role="administrator", source="invitation"
            )
        )
        await db.commit()
    async with client(env) as api:
        proof, exchange = await start(env, api, monkeypatch, web)
        assert (await approve(web, proof, WRITE)).status_code == 200
        result = (await api.post(BASE + "/login/exchange", json=exchange)).json()
        headers = bearer(result)
        organizations = (await api.get(BASE + "/organizations", headers=headers)).json()
        assert organizations["total"] == 1
        assert organizations["items"][0]["org_id"] == str(web.tenant.id)
        assert "skills.write" in organizations["items"][0]["permissions"]
        for suffix in ("/permissions", "/skills", "/experts", "/mcp/services"):
            response = await api.get(BASE + f"/organizations/{other.id}" + suffix, headers=headers)
            assert response.status_code == 403, response.text
            assert response.json()["error"]["code"] == "organization_not_granted"
        response = await api.post(
            BASE + f"/organizations/{other.id}/experts",
            json={"content": content()},
            headers={**headers, "X-Management-Request-ID": str(uuid4())},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "organization_not_granted"
        renewed = await api.post(
            BASE + "/refresh",
            json={"refresh_token": result["refresh_token"], "request_id": str(uuid4())},
        )
        assert renewed.status_code == 200
        me = (await api.get(BASE + "/me", headers=bearer(renewed.json()))).json()
        assert me["authorized_org_ids"] == [str(web.tenant.id)]
        assert me["scope"] == WRITE


@pytest.mark.parametrize(
    "headers", [{"origin": "https://other.example.com"}, {"x-csrf-token": "wrong"}]
)
async def test_consent_requires_browser_origin_and_csrf(env, monkeypatch, headers):
    web = await env.client()
    async with client(env) as api:
        proof, _ = await start(env, api, monkeypatch, web)
        for endpoint in ("context", "decision"):
            payload = (
                proof
                if endpoint == "context"
                else {**proof, "approve": True, "org_ids": [str(web.tenant.id)]}
            )
            assert (
                await web.api.post(WEB + "/" + endpoint, json=payload, headers=headers)
            ).status_code == 403
        assert (await api.post(WEB + "/context", json=proof)).status_code == 403


async def test_decline_expiry_and_wrong_state_never_issue_session(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        proof, exchange = await start(env, api, monkeypatch, web)
        assert (
            await web.api.post(WEB + "/context", json={**proof, "state": "x" * 43})
        ).status_code == 404
        response = await web.api.post(WEB + "/decision", json={**proof, "approve": False})
        assert response.status_code == 200
        assert "error=access_denied" in response.json()["redirect_url"]
        assert (await api.post(BASE + "/login/exchange", json=exchange)).status_code == 401
        proof, exchange = await start(env, api, monkeypatch, web)
        async with env.sessions() as db:
            attempt = await db.get(ManagementLogin, UUID(proof["attempt_id"]))
            attempt.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await approve(web, proof)).status_code == 410
        async with env.sessions() as db:
            assert not (await db.scalars(select(ManagementSession))).all()


async def test_native_identity_must_match_browser_approval(env, monkeypatch):
    web = await env.client()
    other = await env.client(tenant=web.tenant)
    async with client(env) as api:
        proof, exchange = await start(env, api, monkeypatch, other)
        assert (await approve(web, proof, WRITE)).status_code == 200
        response = await api.post(BASE + "/login/exchange", json=exchange)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "consent_identity_mismatch"
        async with env.sessions() as db:
            assert not (await db.scalars(select(ManagementSession))).all()


@pytest.mark.parametrize("role,platform", [("member", False), ("member", True)])
async def test_no_implicit_organization_authority_from_requested_scope_or_platform_role(
    env, monkeypatch, role, platform
):
    web = await env.client(role=role)
    if platform:
        env.provider.settings.platform_edition = "saas"
        async with env.sessions() as db:
            db.add(PlatformOperator(user_id=web.user.id, status="active"))
            await db.commit()
    async with client(env) as api:
        proof, _ = await start(env, api, monkeypatch, web)
        context = await web.api.post(WEB + "/context", json=proof)
        assert context.json()["organizations"] == []
        assert (await approve(web, proof, WRITE)).status_code == 403


async def test_membership_and_platform_switch_rechecked_after_approval(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        proof, exchange = await start(env, api, monkeypatch, web)
        assert (await approve(web, proof, WRITE)).status_code == 200
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.role = "member"
            await db.commit()
        assert (await api.post(BASE + "/login/exchange", json=exchange)).status_code == 403
        env.provider.settings.management_enabled = False
        assert (await web.api.post(WEB + "/context", json=proof)).status_code == 503


async def test_legacy_clients_cannot_request_new_write_sessions(env):
    async with client(env) as api:
        response = await api.post(
            BASE + "/login/start",
            json={
                "contract_version": 1,
                "scope": WRITE,
                "device_name": "Legacy CLI",
                "redirect_uri": "http://127.0.0.1:49161/actvero/cli/callback",
                "code_challenge": pkce(secrets.token_urlsafe(32)),
            },
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "client_upgrade_required"
