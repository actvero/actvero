# ruff: noqa: F811
"""Per-tab contexts with real PostgreSQL isolation; external identity and mail are mocked."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from test_identity_access import env, exchange_as  # noqa: F401
from test_platform_onboarding import invite, platform

from app.modules.auth.models import OrganizationOpeningFlow, WebSession
from app.modules.members.models import Membership
from app.modules.tenants.models import OrganizationInvitation, OrganizationOpening, Tenant

pytestmark = pytest.mark.asyncio


async def flow_for(actor, invitation=None):
    payload = {"invitation": bool(invitation)}
    if invitation:
        payload["token"] = invitation["invite_url"].split("#")[1]
    response = await actor.api.post("/api/v1/organization-onboarding/flows", json=payload)
    assert response.status_code == 200, response.text
    return response.json()["flow_id"]


def endpoint(action, flow, invitation=True):
    return (
        f"/api/v1/organization-onboarding/{action}?flow={flow}&invitation={str(invitation).lower()}"
    )


async def complete(actor, flow, name="新组织", user_id=None, invitation=True):
    return await actor.api.post(
        endpoint("submit", flow, invitation),
        json={
            "organization_name": name,
            "invitation": invitation,
            "confirmed_user_id": str(user_id or actor.user.id),
        },
    )


async def test_two_invites_in_one_browser_keep_drafts_and_completions_separate(env):
    operator = await platform(env)
    receiver = await env.client(joined=False)
    links = [await invite(operator), await invite(operator)]
    flows = [await flow_for(receiver, link) for link in links]
    assert flows[0] != flows[1]
    for flow, name in zip(flows, ["组织甲", "组织乙"], strict=True):
        response = await receiver.api.put(endpoint("draft", flow), json={"organization_name": name})
        assert response.status_code == 200
    for flow, name in zip(flows, ["组织甲", "组织乙"], strict=True):
        data = (await receiver.api.get(endpoint("current", flow))).json()
        assert data["organization_name"] == name and data["account"]["id"] == str(receiver.user.id)
        assert data["resume"] is False
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 0
    first = await complete(receiver, flows[0], "组织甲")
    assert first.status_code == 200, first.text
    assert (await receiver.api.get(endpoint("current", flows[1]))).json()["state"] == "form"
    second = await complete(receiver, flows[1], "组织乙")
    assert (
        second.status_code == 200
        and first.json()["organization_id"] != second.json()["organization_id"]
    )
    assert (await complete(receiver, flows[0])).json()["organization_id"] == first.json()[
        "organization_id"
    ]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 2
        for link in links:
            assert (
                await db.get(OrganizationInvitation, link["invitation"]["id"])
            ).status == "accepted"


async def test_flow_requires_own_session_and_explicit_current_account(env):
    operator = await platform(env)
    a = await env.client(joined=False)
    b = await env.client(joined=False)
    link = await invite(operator)
    flow = await flow_for(a, link)
    assert (await b.api.get(endpoint("current", flow))).status_code == 410
    assert (await complete(b, flow)).status_code == 410
    assert (await a.api.get(endpoint("current", str(uuid4())))).status_code == 410
    missing_confirmation = await a.api.post(
        endpoint("submit", flow), json={"organization_name": "新组织", "invitation": True}
    )
    assert missing_confirmation.status_code == 409
    # A separate tab has changed the browser's authenticated identity.
    async with env.sessions() as db:
        session = await db.get(WebSession, a.session.id)
        session.identity_id = b.identity.id
        await db.commit()
    assert (await complete(a, flow)).status_code == 409
    data = (await a.api.get(endpoint("current", flow))).json()
    assert data["account"]["id"] == str(b.user.id)
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 0
        assert (await db.get(OrganizationInvitation, link["invitation"]["id"])).status == "pending"
    result = await complete(a, flow, user_id=b.user.id)
    assert result.status_code == 200
    async with env.sessions() as db:
        member = await db.scalar(
            select(Membership).where(Membership.tenant_id == result.json()["organization_id"])
        )
        assert member.user_id == b.user.id


async def test_registration_without_org_then_login_still_requires_explicit_opening(env):
    operator = await platform(env)
    receiver = await env.client(joined=False)
    async with env.sessions() as db:
        (await db.get(WebSession, receiver.session.id)).identity_id = None
        await db.commit()
    env.provider.create_managed_user = AsyncMock(return_value=("new-opening-account", False))
    env.provider.settings.smtp_host = None
    link = await invite(operator)
    flow = await flow_for(receiver, link)
    response = await receiver.api.post(
        endpoint("register", flow),
        json={
            "name": "新管理员",
            "email": "new-flow@example.com",
            "password": "private-password-123",
            "invitation": True,
        },
    )
    assert response.status_code == 200, response.text
    assert (await receiver.api.get(endpoint("current", flow))).json()["state"] == "login"
    async with env.sessions() as db:
        opening = await db.scalar(select(OrganizationOpening))
        assert opening.organization_name == "" and "private-password" not in str(opening.__dict__)
        assert (await db.get(OrganizationInvitation, link["invitation"]["id"])).status == "pending"
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    await receiver.api.get(
        "/api/v1/auth/login", params={"next": "/organization-invite", "flow": flow}
    )
    state = env.provider.authorization.call_args.args[0]
    exchange_as(env, "new-opening-account", "new-flow@example.com")
    callback = await receiver.api.get(
        "/api/v1/auth/callback", params={"state": state, "code": "test"}
    )
    assert callback.headers["location"] == f"/organization-invite?flow={flow}"
    session = (await receiver.api.get("/api/v1/auth/session")).json()
    receiver.api.headers["x-csrf-token"] = session["csrf"]
    for _ in range(2):
        current = await receiver.api.get(endpoint("current", flow))
        assert current.json()["state"] == "form" and current.json()["resume"] is False
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 0
    assert (await complete(receiver, flow, user_id=session["user"]["id"])).status_code == 200


async def test_stale_login_returns_to_its_flow_without_replacing_new_login(env):
    operator = await platform(env)
    receiver = await env.client(joined=False)
    a = await flow_for(receiver, await invite(operator))
    b = await flow_for(receiver, await invite(operator))
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    env.provider.exchange = AsyncMock()
    await receiver.api.get("/api/v1/auth/login", params={"next": "/organization-invite", "flow": a})
    state_a = env.provider.authorization.call_args.args[0]
    await receiver.api.get("/api/v1/auth/login", params={"next": "/organization-invite", "flow": b})
    state_b = env.provider.authorization.call_args.args[0]
    response = await receiver.api.get(
        "/api/v1/auth/callback", params={"state": state_a, "code": "test"}
    )
    assert response.headers["location"] == f"/organization-invite?flow={a}&login_error=callback"
    env.provider.exchange.assert_not_awaited()
    response = await receiver.api.get(
        "/api/v1/auth/callback", params={"state": state_b, "error": "access_denied"}
    )
    assert response.headers["location"] == f"/organization-invite?flow={b}&login_error=cancelled"
    assert (
        await receiver.api.get("/api/v1/auth/login", params={"next": "/", "flow": a})
    ).status_code == 400


async def test_verification_uses_flow_return_without_consuming_invite_and_logout_removes_flows(env):
    operator = await platform(env)
    receiver = await env.client(joined=False)
    await operator.api.put(
        "/api/v1/platform/registration", json={"mode": "invite", "invitation_verify_email": True}
    )
    link = await invite(operator)
    flow = await flow_for(receiver, link)
    assert (await receiver.api.post(endpoint("verify-email", flow))).status_code == 200
    env.provider.verify_email.assert_awaited_once_with(
        receiver.identity.subject, f"/api/v1/organization-onboarding/verified/{flow}"
    )
    response = await receiver.api.get(f"/api/v1/organization-onboarding/verified/{flow}")
    assert response.headers["location"] == f"/organization-invite?flow={flow}"
    assert (await receiver.api.post(endpoint("check-email", flow))).status_code == 200
    async with env.sessions() as db:
        assert (await db.get(OrganizationInvitation, link["invitation"]["id"])).status == "pending"
    await receiver.api.post("/api/v1/auth/logout")
    async with env.sessions() as db:
        assert await db.get(OrganizationOpeningFlow, flow) is None


async def test_incremental_migration_keeps_existing_invites_and_sessions(env):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    operator = await platform(env)
    link = await invite(operator)
    engine = env.app.state.database.engine
    async with engine.begin() as conn:
        # The fixture owns a randomly named schema, never an application schema.
        schema = await conn.scalar(text("SELECT current_schema()"))
        assert schema.startswith("test_identity_")
        await conn.execute(text("DROP TABLE organization_opening_flows"))

        def migrate(connection):
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
            config.attributes["connection"] = connection
            command.stamp(config, "99t_organization_onboarding")
            command.upgrade(config, "100u_opening_flows")

        await conn.run_sync(migrate)
        assert (
            await conn.scalar(text("SELECT version_num FROM alembic_version"))
            == "100u_opening_flows"
        )
    async with env.sessions() as db:
        assert (await db.get(OrganizationInvitation, link["invitation"]["id"])).status == "pending"
        assert await db.get(WebSession, operator.session.id) is not None
    assert await flow_for(operator, link)


async def test_revocation_and_public_policy_are_still_checked_per_flow(env):
    operator = await platform(env)
    receiver = await env.client(joined=False)
    link = await invite(operator)
    flow = await flow_for(receiver, link)
    await operator.api.post(
        "/api/v1/platform/organization-invitations/" + link["invitation"]["id"] + "/revoke"
    )
    assert (await receiver.api.get(endpoint("current", flow))).json()["state"] == "expired"
    assert (await complete(receiver, flow)).status_code == 410
    public = await flow_for(receiver)
    assert (await complete(receiver, public, invitation=False)).status_code == 403
    await operator.api.put("/api/v1/platform/registration", json={"mode": "approval"})
    assert (await complete(receiver, public, invitation=False)).json()["state"] == "pending"
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 0
