"""Reusable quota templates and explicit, versioned member assignments."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from test_identity_access import env as identity_env

from app.modules.audit.models import AuditEvent
from app.modules.auth.models import WebSession
from app.modules.members.models import Membership
from app.modules.quota.models import QuotaAssignment
from app.modules.quota.service import matching_policies
from app.modules.tenants.models import Tenant

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/quota/policies"


def hours(points="100", duration=5):
    return {"kind": "fixed_hours", "hours": duration, "points": points}


def week(points="800"):
    return hours(points, 168)


async def create(admin, **kwargs):
    response = await admin.api.post(
        BASE,
        json={"name": "默认", "is_default": True, "mode": "limited", "rules": [hours(), week()]}
        | kwargs,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def edit(admin, policy, **kwargs):
    return await admin.api.put(
        BASE + "/" + policy["id"],
        json={k: policy[k] for k in ("name", "is_default", "mode", "rules", "version")} | kwargs,
    )


async def matches(admin):
    response = await admin.api.get("/api/v1/quota/matches")
    assert response.status_code == 200, response.text
    return {member["member_id"]: member for member in response.json()["items"]}


async def assign(admin, member, policy, version=0):
    return await admin.api.put(
        f"/api/v1/quota/members/{member.member.id}/assignment",
        json={
            "policy_id": policy["id"] if policy else None,
            "version": version,
        },
    )


async def test_templates_and_default_inheritance_include_future_members(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    assert (await matches(admin))[str(member.member.id)]["selected"] is None
    template = await create(admin, name="高额度", is_default=False)
    assert (await matches(admin))[str(member.member.id)]["selected"] is None
    default = await create(admin)
    initial = (await matches(admin))[str(member.member.id)]
    assert initial["selected"]["id"] == default["id"]
    assert initial["assigned"] is None and initial["assignment_version"] == 0
    assert "priority" not in initial["selected"] and "matched" not in initial
    newcomer = await env.client(role="member", tenant=admin.tenant)
    assert (await matches(admin))[str(newcomer.member.id)]["selected"]["id"] == default["id"]
    assert template["rules"] == [hours(), week()]


async def test_member_has_one_policy_and_can_explicitly_use_unlimited(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    default = await create(admin)
    unlimited = await create(admin, name="不限额度", is_default=False, mode="unlimited", rules=[])
    response = await assign(admin, member, unlimited)
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["assigned"]["id"] == unlimited["id"]
    assert value["selected"]["mode"] == "unlimited" and value["rules"] == []
    assert (await matches(admin))[str(admin.member.id)]["selected"]["id"] == default["id"]
    assert (await assign(admin, member, None, 1)).status_code == 200
    value = (await matches(admin))[str(member.member.id)]
    assert value["assigned"] is None and value["selected"]["id"] == default["id"]
    assert value["assignment_version"] == 2
    assert (await assign(admin, member, unlimited, 0)).status_code == 409
    async with env.sessions() as db:
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "quota.member.assign"))
        )
        assert len(events) == 2
        assert (await db.get(QuotaAssignment, member.member.id)).policy_id is None


async def test_policy_validation_zero_limits_and_default_identity(env):
    admin = await env.client()
    default = await create(admin)
    for bad in (
        {"rules": []},
        {"rules": [hours(), hours()]},
        {"rules": [hours("-1")]},
        {"rules": [hours("NaN")]},
        {"rules": [hours("1e6")]},
        {"rules": [hours("1", 0)]},
        {"rules": [hours("1", 721)]},
        {"rules": [week() | {"timezone": "UTC"}]},
        {"mode": "unlimited", "rules": [hours()]},
        {"mode": "unknown"},
        {"priority": 99},
        {"member_ids": []},
        {"is_default": "false"},
    ):
        response = await admin.api.post(BASE, json={"name": "new", "rules": [hours()]} | bad)
        assert response.status_code == 422, (bad, response.text)
    changed = await edit(admin, default, rules=[hours("0"), week("0.000000000001")])
    assert changed.status_code == 200
    assert changed.json()["rules"][0]["points"] == "0"
    assert (await edit(admin, changed.json(), is_default=False)).status_code == 422
    assert (await edit(admin, default, name="stale edit")).status_code == 409


async def test_assignment_scope_permissions_csrf_and_inactive_members(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        foreign_tenant = Tenant(name="其他组织")
        db.add(foreign_tenant)
        await db.commit()
    foreign = await env.client(tenant=foreign_tenant)
    async with env.sessions() as db:
        for owner in (admin, member, foreign):
            session = await db.get(WebSession, owner.session.id)
            session.tenant_id = owner.tenant.id
        await db.commit()
    default = await create(admin)
    foreign_policy = await create(foreign)
    path = f"/api/v1/quota/members/{member.member.id}/assignment"
    body = {"policy_id": default["id"], "version": 0}
    assert (await member.api.put(path, json=body)).status_code == 403
    assert (await foreign.api.put(path, json=body)).status_code == 404
    assert (
        await admin.api.put(path, json=body, headers={"x-csrf-token": "wrong"})
    ).status_code == 403
    assert (
        await admin.api.put(path, json=body, headers={"origin": "https://foreign.example"})
    ).status_code == 403
    assert (await assign(admin, member, foreign_policy)).status_code == 404
    for client in (member,):
        assert (await client.api.get(BASE)).status_code == 403
        assert (await client.api.get("/api/v1/quota/matches")).status_code == 403
        assert (await edit(client, default)).status_code == 403
    async with env.sessions() as db:
        target = await db.get(Membership, member.member.id)
        target.status = "paused"
        await db.commit()
        assert await matching_policies(db, admin.tenant.id, member.member.id) == []
        assert await matching_policies(db, uuid4(), member.member.id) == []
    assert (await assign(admin, member, default)).status_code == 422
    assert (await assign(admin, member, None)).status_code == 200


async def test_archive_requires_reassignment_and_retains_default(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    default = await create(admin)
    policy = await create(admin, name="临时", is_default=False)
    assert (await assign(admin, member, policy)).status_code == 200
    path = BASE + "/" + policy["id"] + "/archive"
    assert (await admin.api.put(path, json={"version": 1, "archived": True})).status_code == 409
    async with env.sessions() as db:
        target = await db.get(Membership, member.member.id)
        target.status = "paused"
        await db.commit()
    paused = (await matches(admin))[str(member.member.id)]
    assert paused["status"] == "paused" and paused["assigned"]["id"] == policy["id"]
    assert (await admin.api.put(path, json={"version": 1, "archived": True})).status_code == 409
    assert (await assign(admin, member, None, 1)).status_code == 200
    assert (await admin.api.put(path, json={"version": 1, "archived": True})).status_code == 200
    assert (await assign(admin, member, policy, 2)).status_code == 404
    await create(admin, name="临时", is_default=False)
    assert (await admin.api.put(path, json={"version": 2, "archived": False})).status_code == 409
    assert (
        await admin.api.put(
            BASE + "/" + default["id"] + "/archive", json={"version": 1, "archived": True}
        )
    ).status_code == 409


async def test_concurrent_assignments_and_default_creation_do_not_silently_overwrite(env):
    admin = await env.client()
    results = await asyncio.gather(
        *[
            admin.api.post(
                BASE,
                json={
                    "name": name,
                    "is_default": True,
                    "rules": [hours()],
                },
            )
            for name in ("默认甲", "默认乙")
        ]
    )
    assert sorted(response.status_code for response in results) == [200, 409]
    member = await env.client(role="member", tenant=admin.tenant)
    one = await create(admin, name="one", is_default=False)
    two = await create(admin, name="two", is_default=False)
    results = await asyncio.gather(assign(admin, member, one), assign(admin, member, two))
    assert sorted(response.status_code for response in results) == [200, 409]
    selected = (await matches(admin))[str(member.member.id)]
    assert selected["assignment_version"] == 1
    assert selected["selected"]["id"] in (one["id"], two["id"])


async def test_policy_search_and_pagination_are_independent_of_member_assignment(env):
    admin = await env.client()
    await create(admin)
    for index in range(21):
        await create(admin, name=f"policy-{index:02}", is_default=False)
    first = (await admin.api.get(BASE)).json()
    second = (await admin.api.get(BASE, params={"page": 2})).json()
    assert first["total"] == 22 and len(first["items"]) == 20 and len(second["items"]) == 2
    assert first["items"][0]["is_default"]
    assert first["default_timezone"] is None
    assert (await admin.api.get(BASE, params={"q": "policy-20"})).json()["total"] == 1
    choices = (await admin.api.get(BASE, params={"assignable_only": True})).json()
    assert choices["total"] == 21 and len(choices["items"]) == 20
    assert not any(policy["is_default"] for policy in choices["items"])


@pytest.mark.parametrize("meter_present", [True, False])
async def test_unlimited_calls_still_record_costs_and_unknown_meter_is_reviewed(
    env, monkeypatch, meter_present
):
    from llm_billing_helpers import billing
    from test_desktop import bearer, native_client
    from test_llm_execution import GATEWAY, configured, credentials, entries, payload, upstream
    from test_mcp import listening

    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    default = await billing(admin, points="0")
    unlimited = await create(admin, name="不限额", is_default=False, mode="unlimited", rules=[])
    assert (await assign(admin, member, unlimited)).status_code == 200
    app, state = upstream()
    if not meter_present:
        state["usage"] = None
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            root, token = await credentials(env, monkeypatch, api, member, model)
            response = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            assert response.status_code == 200, response.text
            view = (await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))).json()
            assert view["status"] == "unlimited" and view["windows"] == []
            row = (await entries(admin))[0]
            assert row["status"] == ("settled" if meter_present else "review")
            assert row["points"] == ("0.0244" if meter_present else None)
            assert (await assign(admin, member, None, 1)).status_code == 200
            limited = (await api.get("/api/v1/desktop/llm/quota", headers=bearer(root))).json()
            assert limited["status"] == "active" and limited["policy"]["id"] == default["id"]
            assert limited["windows"][0]["remaining"] == "0"
            response = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            assert response.status_code == 429 and len(state["calls"]) == 1
