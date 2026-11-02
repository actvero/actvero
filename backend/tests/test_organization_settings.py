"""Organization settings and installation authority use real isolated PostgreSQL schemas."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from test_identity_access import env  # noqa: F401

from app.modules.audit.models import AuditEvent
from app.modules.auth.service import now
from app.modules.client_distribution import worker
from app.modules.client_distribution.models import ClientArtifact, ClientJob
from app.modules.members.models import Membership
from app.modules.tenants.models import Installation, PlatformOperator, Tenant

pytestmark = pytest.mark.asyncio


async def owner(env):  # noqa: F811
    actor = await env.client()
    async with env.sessions() as db:
        install = await db.get(Installation, 1)
        install.issuer = actor.identity.issuer
        install.subject = actor.identity.subject
        await db.commit()
    return actor


async def test_setup_owner_can_manage_system_settings_without_platform_authority(env):  # noqa: F811
    actor = await owner(env)
    session = (await actor.api.get("/api/v1/auth/session")).json()
    assert session["instance_administrator"] is True
    assert session["platform_operator"] is False
    for path in (
        "branding/settings",
        "settings",
        "portal",
        "cli",
        "mail",
        "mail/preview",
        "object-storage",
        "downloads",
        "client-distribution/releases",
        "client-distribution/heads",
    ):
        response = await actor.api.get("/api/v1/platform/" + path)
        assert response.status_code == 200, (path, response.text)
    response = await actor.api.put("/api/v1/platform/cli", json={"enabled": True})
    assert response.status_code == 200 and response.json()["enabled"] is True
    brand = (await actor.api.get("/api/v1/platform/branding/settings")).json()
    response = await actor.api.put(
        "/api/v1/platform/branding/settings",
        json={"platform_name": "实例品牌", "revision": brand["revision"], "assets": {}},
    )
    assert response.status_code == 200, response.text
    assert (await actor.api.get("/api/v1/platform/branding")).json()["name"] == "实例品牌"
    response = await actor.api.put(
        f"/api/v1/platform/client-distribution/releases/{uuid4()}",
        json={"expected_revision": 0, "version": "1.0.0", "notes": "本地发布草稿"},
    )
    assert response.status_code == 200 and response.json()["status"] == "draft", response.text
    assert (
        await actor.api.put(
            "/api/v1/platform/cli", json={"enabled": False}, headers={"x-csrf-token": "wrong"}
        )
    ).status_code == 403
    for path in ("organizations", "organization-invitations", "registration", "applications"):
        assert (await actor.api.get("/api/v1/platform/" + path)).status_code == 404
    assert (
        await actor.api.post(
            "/api/v1/platform/organizations", json={"organization_name": "第二组织"}
        )
    ).status_code == 404


async def test_other_admin_and_matching_email_do_not_inherit_instance_authority(env):  # noqa: F811
    actor = await owner(env)
    other = await env.client(tenant=actor.tenant, email=actor.user.email)
    session = (await other.api.get("/api/v1/auth/session")).json()
    assert session["instance_administrator"] is False
    for path in (
        "branding/settings",
        "mail",
        "cli",
        "object-storage",
        "client-distribution/releases",
    ):
        assert (await other.api.get("/api/v1/platform/" + path)).status_code == 403
    assert (await other.api.put("/api/v1/platform/cli", json={"enabled": True})).status_code == 403
    assert (await other.api.get(other.path + "/settings")).status_code == 200
    async with env.sessions() as db:
        install = await db.get(Installation, 1)
        install.issuer = "https://different-issuer.example/realms/team"
        await db.commit()
    assert (await actor.api.get("/api/v1/platform/cli")).status_code == 403


@pytest.mark.parametrize("change", ["paused", "removed", "demoted", "revoked", "tenant_paused"])
async def test_instance_authority_tracks_current_membership(env, change):  # noqa: F811
    actor = await owner(env)
    assert (await actor.api.get("/api/v1/platform/cli")).status_code == 200
    async with env.sessions() as db:
        member = await db.get(Membership, actor.member.id)
        if change in {"paused", "removed"}:
            member.status = change
        elif change == "demoted":
            member.role = "member"
        elif change == "revoked":
            member.revoked_at = now() + timedelta(seconds=1)
        else:
            (await db.get(Tenant, actor.tenant.id)).active = False
        await db.commit()
    assert (await actor.api.get("/api/v1/auth/session")).json()["instance_administrator"] is False
    assert (await actor.api.get("/api/v1/platform/cli")).status_code == 403


async def test_organization_rename_persists_and_conflicting_draft_is_rejected(env):  # noqa: F811
    actor = await owner(env)
    path = actor.path + "/settings"
    before = (await actor.api.get(path)).json()
    response = await actor.api.put(
        path, json={"name": " 新组织名称 ", "expected_name": before["name"]}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {**before, "name": "新组织名称"}
    assert (await actor.api.get("/api/v1/auth/session")).json()["organization"][
        "name"
    ] == "新组织名称"
    assert (
        await actor.api.put(path, json={"name": "过期草稿", "expected_name": before["name"]})
    ).status_code == 409
    async with env.sessions() as db:
        assert (await db.get(Tenant, actor.tenant.id)).name == "新组织名称"
        audit = await db.scalar(select(AuditEvent))
        assert audit.action == "organization.settings.updated"
        assert audit.tenant_id == actor.tenant.id and audit.details == {
            "previous_name": before["name"]
        }


async def test_organization_settings_enforce_membership_csrf_and_allowed_fields(env):  # noqa: F811
    actor = await owner(env)
    member = await env.client(role="member", tenant=actor.tenant)
    outsider = await env.client(joined=False)
    path = actor.path + "/settings"
    payload = {"name": "合法组织名", "expected_name": actor.tenant.name}
    for client in (member, outsider):
        assert (await client.api.get(path)).status_code == 403
        assert (await client.api.put(path, json=payload)).status_code == 403
    async with env.sessions() as db:
        (await db.get(Membership, actor.member.id)).revoked_at = now() + timedelta(seconds=1)
        await db.commit()
    assert (await actor.api.get(path)).status_code == 401
    async with env.sessions() as db:
        (await db.get(Membership, actor.member.id)).revoked_at = None
        await db.commit()
    assert (await actor.api.get(f"/api/v1/enterprises/{uuid4()}/settings")).status_code == 403
    assert (
        await actor.api.put(path, json=payload, headers={"x-csrf-token": "wrong"})
    ).status_code == 403
    for fields in ({"active": False}, {"name": "a"}, {"name": "\nInject"}, {"name": " " * 3}):
        assert (await actor.api.put(path, json=payload | fields)).status_code == 422
    actor.api.cookies.clear()
    assert (await actor.api.get(path)).status_code == 401
    assert (await actor.api.get("/api/v1/platform/cli")).status_code == 401


async def test_concurrent_organization_edit_keeps_one_revision(env):  # noqa: F811
    actor = await owner(env)
    second = await env.client(tenant=actor.tenant)
    results = await asyncio.gather(
        *[
            client.api.put(
                actor.path + "/settings",
                json={"name": name, "expected_name": actor.tenant.name},
            )
            for client, name in ((actor, "名称甲"), (second, "名称乙"))
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 409]


async def test_saas_operator_keeps_settings_but_not_implicit_organization_access(env):  # noqa: F811
    actor = await owner(env)
    operator = await env.client(joined=False)
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        db.add(PlatformOperator(user_id=operator.user.id))
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        db.add(Tenant(name="已有名称"))
        await db.commit()
    assert (await actor.api.get("/api/v1/auth/session")).json()["instance_administrator"] is False
    assert (await actor.api.get("/api/v1/platform/cli")).status_code == 403
    assert (await operator.api.get("/api/v1/platform/cli")).status_code == 200
    assert (await operator.api.get(actor.path + "/settings")).status_code == 403
    assert (await actor.api.get(actor.path + "/settings")).status_code == 200
    assert (
        await actor.api.put(
            actor.path + "/settings", json={"name": "已有名称", "expected_name": actor.tenant.name}
        )
    ).status_code == 409


@pytest.mark.parametrize("revoke", ["none", "before", "during"])
async def test_community_artifact_jobs_recheck_instance_authority(env, monkeypatch, revoke):  # noqa: F811
    from test_client_distribution import add, files, release

    actor = await owner(env)
    row = await release(actor.api)
    payload, _ = files(monkeypatch)
    artifact = await add(actor.api, row, "payload", payload)

    async def revoke_owner():
        async with env.sessions() as db:
            (await db.get(Membership, actor.member.id)).revoked_at = now()
            await db.commit()

    if revoke == "before":
        await revoke_owner()
    elif revoke == "during":

        async def check_range(*args):
            await revoke_owner()
            return True

        monkeypatch.setattr(worker, "check_range", check_range)
    assert await worker.run_once(env.app)
    async with env.sessions() as db:
        job = await db.scalar(select(ClientJob))
        item = await db.get(ClientArtifact, UUID(artifact["id"]))
        assert job.status == ("succeeded" if revoke == "none" else "failed")
        assert item.status == ("ready" if revoke == "none" else "failed")
