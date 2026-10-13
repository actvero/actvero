from uuid import uuid4

import pytest
from test_identity_access import env as env

pytestmark = pytest.mark.asyncio


async def test_member_selection_search_paging_and_access(env):
    admin = await env.client()
    members = [await env.client(role="member", email=f"pick{i:02}@example.com") for i in range(22)]
    ids = [str(m.member.id) for m in members]
    path = admin.path + "/members/selection"
    response = await admin.api.post(path, json={"member_ids": ids + [str(uuid4())]})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == 22
    assert len(response.json()["items"]) == 20
    second = (await admin.api.post(path, json={"member_ids": ids, "page": 2})).json()
    assert len(second["items"]) == 2
    assert not {r["id"] for r in response.json()["items"]} & {r["id"] for r in second["items"]}
    searched = (await admin.api.post(path, json={"member_ids": ids, "q": "pick21@"})).json()
    assert searched["total"] == 1 and searched["items"][0]["id"] == ids[21]
    assert (await admin.api.post(path, json={"member_ids": []})).json()["items"] == []
    assert (await members[0].api.post(path, json={"member_ids": ids})).status_code == 403
    assert (
        await admin.api.post(
            f"/api/v1/enterprises/{uuid4()}/members/selection", json={"member_ids": ids}
        )
    ).status_code == 403
    assert (await admin.api.post(path, json={"member_ids": ids * 50})).status_code == 422


async def test_member_selection_paused_members_and_mcp_grants(env):
    from app.modules.members.models import Membership

    admin = await env.client()
    member = await env.client(role="member")
    other = await env.client(role="member")
    member_id = str(member.member.id)
    path = admin.path + "/members/selection"
    body = {
        "name": "范围验证",
        "transport": "builtin",
        "audience": "selected",
        "member_ids": [member_id],
    }
    created = await admin.api.post("/api/v1/mcp/services", json=body)
    assert created.status_code == 200, created.text
    service = created.json()
    service_path = "/api/v1/mcp/services/" + service["id"]
    enabled = await admin.api.put(
        service_path, json={**body, "enabled": True, "version": service["version"]}
    )
    assert enabled.status_code == 200
    assert len((await member.api.get("/api/v1/mcp/services")).json()["items"]) == 1
    assert (await other.api.get("/api/v1/mcp/services")).json()["items"] == []
    opened = await admin.api.put(
        service_path,
        json={
            **body,
            "audience": "organization",
            "member_ids": [],
            "enabled": True,
            "version": enabled.json()["version"],
        },
    )
    assert opened.status_code == 200
    assert len((await other.api.get("/api/v1/mcp/services")).json()["items"]) == 1
    closed = await admin.api.put(
        service_path,
        json={**body, "member_ids": [], "enabled": True, "version": opened.json()["version"]},
    )
    assert closed.status_code == 200
    assert (await member.api.get("/api/v1/mcp/services")).json()["items"] == []
    async with env.sessions() as db:
        row = await db.get(Membership, member.member.id)
        row.status = "paused"
        await db.commit()
    resolved = (await admin.api.post(path, json={"member_ids": [member_id]})).json()
    assert resolved["items"][0]["status"] == "paused"
    rejected = await admin.api.put(service_path, json={**body, "version": closed.json()["version"]})
    assert rejected.status_code == 422
    rejected = await admin.api.put(
        service_path,
        json={**body, "member_ids": [str(uuid4())], "version": closed.json()["version"]},
    )
    assert rejected.status_code == 422
