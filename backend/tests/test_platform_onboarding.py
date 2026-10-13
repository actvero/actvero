# ruff: noqa: F811
"""Real isolated PostgreSQL transactions, with only external Keycloak/mail mocked."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select, text
from test_identity_access import env  # noqa: F401

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import WebSession
from app.modules.members.models import Membership
from app.modules.tenants.models import (
    Installation,
    OrganizationInvitation,
    OrganizationOpening,
    PlatformOperator,
    Tenant,
)
from app.modules.users.models import LoginIdentity

pytestmark = pytest.mark.asyncio


async def platform(env):
    env.provider.settings.platform_edition = "saas"
    actor = await env.client(joined=False)
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        install = await db.get(Installation, 1)
        install.platform_operator_user_id = actor.user.id
        db.add(PlatformOperator(user_id=actor.user.id))
        await db.commit()
    return actor


async def invite(actor, **kwargs):
    result = await actor.api.post("/api/v1/platform/organization-invitations", json=kwargs)
    assert result.status_code == 200, result.text
    return result.json()


async def claim(actor, invitation):
    result = await actor.api.post(
        "/api/v1/organization-invitations/claim",
        json={"token": invitation["invite_url"].split("#")[1]},
    )
    assert result.status_code == 200, result.text


async def submit(actor, name="新组织", invitation=True):
    return await actor.api.post(
        "/api/v1/organization-onboarding/submit",
        json={"organization_name": name, "invitation": invitation},
    )


async def test_no_mail_invite_existing_unverified_identity_and_replay(env):
    operator = await platform(env)
    env.provider.settings.smtp_host = None
    receiver = await env.client(joined=False)
    async with env.sessions() as db:
        identity = await db.get(LoginIdentity, receiver.identity.id)
        identity.email_verified = False
        await db.commit()
    link = await invite(operator)
    await claim(receiver, link)
    preview = (
        await receiver.api.get("/api/v1/organization-onboarding/current?invitation=true")
    ).json()
    assert preview["state"] == "form" and not preview["verify_email"]
    responses = await asyncio.gather(submit(receiver), submit(receiver))
    assert [r.status_code for r in responses] == [200, 200]
    assert responses[0].json()["organization_id"] == responses[1].json()["organization_id"]
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 1
        assert not (await db.get(LoginIdentity, receiver.identity.id)).email_verified
        assert (
            await db.get(OrganizationInvitation, link["invitation"]["id"])
        ).token_ciphertext is None
    assert (
        await operator.api.post(
            "/api/v1/platform/organization-invitations/" + link["invitation"]["id"] + "/link"
        )
    ).status_code == 409


async def test_opening_link_repeated_visits_and_failed_submit_do_not_consume_it(env):
    operator = await platform(env)
    visitor = await env.client(joined=False)
    receiver = await env.client(joined=False)
    link = await invite(operator)
    for actor in (visitor, visitor, receiver):
        await claim(actor, link)
        preview = await actor.api.get("/api/v1/organization-onboarding/current?invitation=true")
        assert preview.status_code == 200 and preview.json()["state"] == "form"
    assert (await submit(receiver, " ")).status_code == 422
    async with env.sessions() as db:
        row = await db.get(OrganizationInvitation, link["invitation"]["id"])
        assert row.status == "pending" and row.accepted_at is None
        assert row.organization_id is None and row.token_ciphertext is not None
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 0
    copied = await operator.api.post(
        "/api/v1/platform/organization-invitations/" + link["invitation"]["id"] + "/link"
    )
    assert copied.status_code == 200 and copied.json()["invite_url"] == link["invite_url"]
    assert (await submit(receiver)).status_code == 200
    async with env.sessions() as db:
        row = await db.get(OrganizationInvitation, link["invitation"]["id"])
        assert row.status == "accepted" and row.accepted_at is not None
        assert row.accepted_by == receiver.user.id and row.token_ciphertext is None
        member = await db.scalar(
            select(Membership).where(
                Membership.tenant_id == row.organization_id,
                Membership.user_id == receiver.user.id,
            )
        )
        assert member.role == "administrator"
    await claim(visitor, link)
    assert (
        await visitor.api.get("/api/v1/organization-onboarding/current?invitation=true")
    ).json()["state"] == "used"
    assert (await submit(visitor)).status_code == 409


async def test_new_account_password_is_forwarded_only_and_existing_is_not_adopted(env):
    operator = await platform(env)
    receiver = await env.client(joined=False)
    async with env.sessions() as db:
        row = await db.get(WebSession, receiver.session.id)
        row.identity_id = None
        await db.commit()
    env.provider.create_managed_user = AsyncMock(return_value=("new-subject", False))
    env.provider.settings.smtp_host = None
    link = await invite(operator)
    await claim(receiver, link)
    body = dict(
        organization_name="无邮件组织",
        name="新用户",
        email="new@example.com",
        password="test-password-12345",
        invitation=True,
    )
    result = await receiver.api.post("/api/v1/organization-onboarding/register", json=body)
    assert result.status_code == 200, result.text
    assert "test-password" not in result.text
    args = env.provider.create_managed_user.await_args
    assert args.args[2] == body["password"] and args.kwargs["temporary"] is False
    async with env.sessions() as db:
        opening = await db.scalar(select(OrganizationOpening))
        assert opening.subject == "new-subject"
        invitation = await db.get(OrganizationInvitation, link["invitation"]["id"])
        assert invitation.status == "pending" and invitation.accepted_at is None
        assert invitation.organization_id is None and invitation.token_ciphertext is not None
        assert body["password"] not in str(opening.__dict__)
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 0
        identity = await db.get(LoginIdentity, receiver.identity.id)
        identity.subject = "new-subject"
        identity.email_verified = False
        row = await db.get(WebSession, receiver.session.id)
        row.identity_id = identity.id
        await db.commit()
    # Reopening after account creation must preserve the draft and usable invitation.
    await claim(receiver, link)
    preview = await receiver.api.get("/api/v1/organization-onboarding/current?invitation=true")
    assert preview.json()["state"] == "form"
    assert preview.json()["organization_name"] == "无邮件组织"
    assert (await submit(receiver, "无邮件组织")).status_code == 200
    async with env.sessions() as db:
        assert (await db.get(OrganizationInvitation, link["invitation"]["id"])).status == "accepted"


async def test_email_invite_requires_matching_verified_recipient(env):
    operator = await platform(env)
    receiver = await env.client(joined=False, email="recipient@example.com")
    other = await env.client(joined=False)
    with patch("app.modules.platform.router.send_mail", AsyncMock()):
        link = await invite(operator, recipient_email="recipient@example.com")
    await claim(other, link)
    assert (await submit(other)).status_code == 403
    await claim(receiver, link)
    async with env.sessions() as db:
        (await db.get(LoginIdentity, receiver.identity.id)).email_verified = False
        await db.commit()
    assert (await submit(receiver)).status_code == 409
    assert (
        await receiver.api.post("/api/v1/organization-onboarding/verify-email?invitation=true")
    ).status_code == 200
    env.provider.verify_email.assert_awaited_once_with(
        receiver.identity.subject, "/organization-invite"
    )
    env.provider.verified_email.return_value = True
    assert (await submit(receiver)).status_code == 200


async def test_invite_is_consumed_by_one_receiver_and_revocation_is_enforced(env):
    operator = await platform(env)
    a = await env.client(joined=False)
    b = await env.client(joined=False)
    link = await invite(operator)
    await claim(a, link)
    await claim(b, link)
    results = await asyncio.gather(submit(a, "组织甲"), submit(b, "组织乙"))
    assert sorted(r.status_code for r in results) == [200, 409]
    revoked = await invite(operator)
    await claim(a, revoked)
    await operator.api.post(
        "/api/v1/platform/organization-invitations/" + revoked["invitation"]["id"] + "/revoke"
    )
    assert (await submit(a, "组织丙")).status_code == 410


async def test_review_does_not_create_organization_until_approved_and_replays(env):
    operator = await platform(env)
    applicant = await env.client(joined=False)
    policy = await operator.api.put("/api/v1/platform/registration", json={"mode": "approval"})
    assert policy.status_code == 200, policy.text
    result = await submit(applicant, "申请组织", invitation=False)
    assert result.status_code == 200 and result.json()["state"] == "pending"
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 0
    rows = (await operator.api.get("/api/v1/platform/applications")).json()["items"]
    path = "/api/v1/platform/applications/" + rows[0]["id"] + "/decision"
    assert (await applicant.api.post(path, json={"approve": True})).status_code == 403
    decisions = await asyncio.gather(
        *[operator.api.post(path, json={"approve": True}) for _ in range(2)]
    )
    assert [x.status_code for x in decisions] == [200, 200]
    assert (await applicant.api.get("/api/v1/organization-onboarding/current")).json()[
        "state"
    ] == "approved"
    assert (
        await operator.api.post(path, json={"approve": False, "reason": "changed"})
    ).status_code == 409
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(Tenant)) == 1


async def test_rejection_has_reason_and_resubmission_preserves_history(env):
    operator = await platform(env)
    applicant = await env.client(joined=False)
    await operator.api.put("/api/v1/platform/registration", json={"mode": "approval"})
    await submit(applicant, invitation=False)
    row = (await operator.api.get("/api/v1/platform/applications")).json()["items"][0]
    path = "/api/v1/platform/applications/" + row["id"] + "/decision"
    assert (await operator.api.post(path, json={"approve": False})).status_code == 422
    assert (
        await operator.api.post(path, json={"approve": False, "reason": "请补充组织名称"})
    ).status_code == 200
    await applicant.api.post("/api/v1/organization-onboarding/restart")
    assert (await submit(applicant, "重新申请", invitation=False)).json()["state"] == "pending"
    assert (await operator.api.get("/api/v1/platform/applications")).json()["total"] == 2


async def test_public_policy_and_verification_enforced_on_backend(env):
    operator = await platform(env)
    applicant = await env.client(joined=False)
    assert (await submit(applicant, invitation=False)).status_code == 403
    env.provider.settings.smtp_host = None
    assert (
        await operator.api.put("/api/v1/platform/registration", json={"mode": "self_service"})
    ).status_code == 409
    env.provider.settings.smtp_host = "test"
    assert (
        await operator.api.put("/api/v1/platform/registration", json={"mode": "self_service"})
    ).status_code == 200
    async with env.sessions() as db:
        (await db.get(LoginIdentity, applicant.identity.id)).email_verified = False
        await db.commit()
    assert (await submit(applicant, invitation=False)).status_code == 409
    env.provider.verified_email.return_value = True
    assert (await submit(applicant, invitation=False)).json()["state"] == "completed"


async def test_platform_can_manage_org_without_impersonating_and_revocation_is_live(env):
    operator = await platform(env)
    owner = await env.client()
    path = owner.path + "/members"
    assert (
        await operator.api.post("/api/v1/auth/workspace", json={"tenant_id": str(owner.tenant.id)})
    ).status_code == 200
    assert (await operator.api.get(path)).status_code == 200
    context = (await operator.api.get("/api/v1/auth/session")).json()
    assert context["organization"]["role"] == "administrator"
    async with env.sessions() as db:
        member = await db.scalar(select(Membership).where(Membership.user_id == operator.user.id))
        assert member.source == "platform"
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "platform.organization.entered")
        )
        assert event.actor_id == operator.user.id
        (await db.get(PlatformOperator, operator.user.id)).status = "paused"
        await db.commit()
    assert (await operator.api.get(path)).status_code == 403


async def test_org_pause_blocks_member_but_retains_operator_management(env):
    operator = await platform(env)
    owner = await env.client()
    other = await env.client(role="member")
    assert (
        await other.api.put(
            "/api/v1/platform/organizations/" + str(owner.tenant.id),
            json={"organization_name": "changed", "active": False},
        )
    ).status_code == 403
    await operator.api.post("/api/v1/auth/workspace", json={"tenant_id": str(owner.tenant.id)})
    result = await operator.api.put(
        "/api/v1/platform/organizations/" + str(owner.tenant.id),
        json={"organization_name": "已暂停组织", "active": False},
    )
    assert result.status_code == 200
    assert (await owner.api.get(owner.path + "/members")).status_code == 403
    assert (await operator.api.get(owner.path + "/members")).status_code == 200


async def test_community_has_no_public_registration(env):
    actor = await env.client()
    assert (await actor.api.get("/api/v1/organization-onboarding/current")).status_code == 404
    assert (
        await actor.api.put("/api/v1/platform/registration", json={"mode": "self_service"})
    ).status_code == 404


async def test_operator_reference_does_not_grant_desktop_or_personal_key(env):
    from types import SimpleNamespace
    from uuid import uuid4

    from app.modules.desktop.service import organization

    operator = await platform(env)
    owner = await env.client()
    await operator.api.post("/api/v1/auth/workspace", json={"tenant_id": str(owner.tenant.id)})
    async with env.sessions() as db:
        tenant, member = await organization(
            db,
            SimpleNamespace(user=operator.user, session=SimpleNamespace(tenant_id=None)),
            platform_edition="saas",
        )
        assert tenant is None and member is None
    response = await operator.api.post(
        "/api/v1/account/access-keys", json={"name": "test", "creation_id": str(uuid4())}
    )
    assert response.status_code == 403 and "membership_required" in response.text


async def test_public_registration_prevents_disabling_identity_mail(env):
    operator = await platform(env)
    await operator.api.put("/api/v1/platform/registration", json={"mode": "approval"})
    current = (await operator.api.get("/api/v1/platform/mail")).json()
    result = await operator.api.put("/api/v1/platform/mail", json={**current, "enabled": False})
    assert result.status_code == 409, result.text


async def test_organization_mail_does_not_depend_on_member_invitation_expiry(env):
    operator = await platform(env)
    env.provider.settings.invitation_hours = None
    policy = await operator.api.put("/api/v1/platform/registration", json={"mode": "self_service"})
    assert policy.status_code == 200 and policy.json()["mail_enabled"]
    with patch("app.modules.platform.router.send_mail", AsyncMock()):
        result = await invite(operator, recipient_email="recipient@example.com")
    assert result["mail_status"] == "sent"
