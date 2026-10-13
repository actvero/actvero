"""Real PostgreSQL configuration and authorization tests; no billing simulation."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_identity_access import env as identity_env

from app.modules.audit.models import AuditEvent
from app.modules.members.models import Membership
from app.modules.quota.models import QuotaPolicy
from app.modules.quota.service import matching_policies

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/quota/policies"


def hours(points="100", duration=5):
    return {"kind": "fixed_hours", "hours": duration, "points": points}


def week(points="800"):
    return {"kind": "calendar_week", "points": points, "timezone": "Asia/Shanghai", "week_start": 0}


async def create(admin, **kwargs):
    r = await admin.api.post(
        BASE, json={"name": "默认", "priority": 0, "rules": [hours(), week()]} | kwargs
    )
    assert r.status_code == 200, r.text
    return r.json()


async def edit(admin, policy, **kwargs):
    return await admin.api.put(
        BASE + "/" + policy["id"],
        json={k: policy[k] for k in ("name", "priority", "rules", "member_ids", "version")}
        | kwargs,
    )


async def matches(admin):
    r = await admin.api.get("/api/v1/quota/matches")
    assert r.status_code == 200
    assert r.json()["enforcement"] == "active"
    return {m["member_id"]: m for m in r.json()["items"]}


async def test_default_timezone_is_readonly_and_independent_of_list_filter(env):
    admin = await env.client()
    before = (await admin.api.get(BASE)).json()
    assert before["default_timezone"] is None
    default = await create(admin)
    filtered = (await admin.api.get(BASE, params={"q": "no-such-policy", "page": 2})).json()
    assert filtered["items"] == []
    assert filtered["default_timezone"] == "Asia/Shanghai"
    assert (await edit(admin, default, rules=[hours()])).status_code == 200
    assert (await admin.api.get(BASE)).json()["default_timezone"] is None


async def test_highest_whole_policy_default_new_members_and_archive_fallback(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    assert (await matches(admin))[str(member.member.id)]["selected"] is None
    default = await create(admin)
    middle = await create(
        admin,
        name="进阶",
        priority=10,
        member_ids=[str(member.member.id)],
        rules=[hours("200"), week("1200")],
    )
    high = await create(
        admin,
        name="高级",
        priority=20,
        member_ids=[str(member.member.id), str(admin.member.id)],
        rules=[week("2000")],
    )
    data = await matches(admin)
    current = data[str(member.member.id)]
    assert [p["priority"] for p in current["matched"]] == [20, 10, 0]
    assert current["rules"] == [week("2000")]  # Never merge the lower policy's hours.
    assert data[str(admin.member.id)]["selected"]["id"] == high["id"]
    newcomer = await env.client(role="member", tenant=admin.tenant)
    assert (await matches(admin))[str(newcomer.member.id)]["selected"]["id"] == default["id"]
    r = await admin.api.put(
        BASE + "/" + high["id"] + "/archive", json={"version": 1, "archived": True}
    )
    assert r.status_code == 200
    assert (await matches(admin))[str(member.member.id)]["selected"]["id"] == middle["id"]
    assert (await matches(admin))[str(admin.member.id)]["selected"]["id"] == default["id"]
    restored = await admin.api.put(
        BASE + "/" + high["id"] + "/archive", json={"version": 2, "archived": False}
    )
    assert restored.status_code == 200
    assert (await matches(admin))[str(member.member.id)]["selected"]["id"] == high["id"]
    async with env.sessions() as db:
        events = list(await db.scalars(select(AuditEvent).where(AuditEvent.action.like("quota.%"))))
        assert {e.action for e in events} == {
            "quota.policy.create",
            "quota.policy.archive",
            "quota.policy.restore",
        }


async def test_default_identity_priority_conflicts_and_optimistic_version(env):
    admin = await env.client()
    before = await admin.api.post(
        BASE,
        json={
            "name": "高",
            "priority": 10,
            "member_ids": [str(admin.member.id)],
            "rules": [hours()],
        },
    )
    assert before.status_code == 409
    default = await create(admin)
    assert (
        await edit(admin, default, priority=10, member_ids=[str(admin.member.id)])
    ).status_code == 422
    assert (
        await admin.api.put(
            BASE + "/" + default["id"] + "/archive", json={"version": 1, "archived": True}
        )
    ).status_code == 409
    jobs = [
        admin.api.post(
            BASE,
            json={
                "name": n,
                "priority": 10,
                "rules": [hours()],
                "member_ids": [str(admin.member.id)],
            },
        )
        for n in ("one", "two")
    ]
    results = await asyncio.gather(*jobs)
    assert sorted(r.status_code for r in results) == [200, 409]
    updated = await edit(admin, default, rules=[hours("0"), week("0.000000000001")])
    assert updated.status_code == 200
    assert updated.json()["rules"] == [hours("0"), week("0.000000000001")]
    assert (await edit(admin, default, name="旧页面覆盖")).status_code == 409
    assert (await admin.api.get(BASE)).json()["total"] == 2


async def test_invalid_rules_members_and_untrusted_access(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    default = await create(admin)
    body = {
        "name": "higher",
        "priority": 10,
        "rules": [hours()],
        "member_ids": [str(member.member.id)],
    }
    for bad in (
        {"member_ids": []},
        {"member_ids": [str(uuid4())]},
        {"rules": []},
        {"rules": [hours(), hours()]},
        {"rules": [hours("-1")]},
        {"rules": [hours("NaN")]},
        {"rules": [hours("1e6")]},
        {"rules": [hours("1", 0)]},
        {"rules": [week() | {"timezone": "bad/time"}]},
        {"rules": [week() | {"week_start": 7}]},
        {"rules": [week(), week()]},
        {"priority": True},
    ):
        r = await admin.api.post(BASE, json=body | bad)
        assert r.status_code == 422, (bad, r.text)
    for client in (member, outsider):
        assert (await client.api.get(BASE)).status_code == 403
        assert (await client.api.get("/api/v1/quota/matches")).status_code == 403
        assert (await client.api.post(BASE, json=body)).status_code == 403
        assert (await edit(client, default, name="denied")).status_code == 403
    assert (
        await admin.api.post(BASE, json=body, headers={"x-csrf-token": "wrong"})
    ).status_code == 403
    assert (
        await admin.api.post(BASE, json=body, headers={"origin": "https://evil.example"})
    ).status_code == 403
    unknown = default | {"id": str(uuid4())}
    assert (await edit(admin, unknown)).status_code == 404
    admin.api.cookies.clear()
    assert (await admin.api.get(BASE)).status_code == 401
    assert (
        await admin.api.get(BASE, headers={"authorization": "Bearer avl_test"})
    ).status_code == 401


async def test_paused_members_do_not_match_and_unrelated_policy_edits_retain_assignment(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    await create(admin)
    high = await create(admin, name="高级", priority=10, member_ids=[str(member.member.id)])
    async with env.sessions() as db:
        row = await db.get(Membership, member.member.id)
        row.status = "paused"
        await db.commit()
        assert await matching_policies(db, admin.tenant.id, member.member.id) == []
        assert await matching_policies(db, uuid4(), member.member.id) == []
    assert str(member.member.id) not in await matches(admin)
    assert (await edit(admin, high, name="高级改名")).status_code == 200
    async with env.sessions() as db:
        row = await db.get(Membership, member.member.id)
        row.status = "active"
        await db.commit()
    assert (await matches(admin))[str(member.member.id)]["selected"]["id"] == high["id"]
    async with env.sessions() as db:
        row = await db.get(Membership, member.member.id)
        row.status = "removed"
        await db.commit()
    assert (await edit(admin, high | {"version": 2})).status_code == 422


async def test_search_pagination_archive_priority_reuse_and_restore_conflict(env):
    admin = await env.client()
    await create(admin)
    for i in range(21):
        await create(admin, name=f"policy-{i}", priority=i + 1, member_ids=[str(admin.member.id)])
    first = (await admin.api.get(BASE)).json()
    assert first["total"] == 22 and len(first["items"]) == 20
    assert first["items"][0]["priority"] == 21
    second = (await admin.api.get(BASE, params={"page": 2})).json()
    assert len(second["items"]) == 2 and second["has_default"]
    assert (await admin.api.get(BASE, params={"q": "%"})).json()["total"] == 0
    p = first["items"][0]
    assert (
        await admin.api.put(
            BASE + "/" + p["id"] + "/archive", json={"version": 1, "archived": True}
        )
    ).status_code == 200
    await create(
        admin, name="replacement", priority=p["priority"], member_ids=[str(admin.member.id)]
    )
    assert (
        await admin.api.put(
            BASE + "/" + p["id"] + "/archive", json={"version": 2, "archived": False}
        )
    ).status_code == 409
    assert (await admin.api.get(BASE, params={"state": "archived"})).json()["total"] == 1
    async with env.sessions() as db:
        assert (await db.get(QuotaPolicy, UUID(p["id"]))).archived
