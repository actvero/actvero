"""Department changes apply to the next resource request with the same credential."""

from unittest.mock import AsyncMock

import pytest
from test_access_keys import create as create_key
from test_access_keys import headers as key_headers
from test_desktop import bearer, login, native_client
from test_desktop_mcp import token
from test_gateway_publication_access import setup as gateway_setup
from test_identity_access import env as identity_env
from test_model_gateway import BASE as GATEWAY
from test_repository_isolation import organizations
from test_workbenches import BASE as WORKBENCHES
from test_workbenches import BINARY, package

from app.modules.desktop.oidc import NativeIdentity

pytestmark = pytest.mark.asyncio
env = identity_env


def organization(actor):
    return f"/api/v1/enterprises/{actor.tenant.id}"


async def department(admin, name, parent=None):
    response = await admin.api.post(
        organization(admin) + "/departments",
        json={"name": name, "parent_id": parent},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def assign(admin, member, department_ids):
    path = organization(admin) + f"/members/{member.member.id}/departments"
    current = (await admin.api.get(path)).json()
    response = await admin.api.put(
        path,
        json={
            "department_ids": department_ids,
            "primary_department_id": department_ids[0] if department_ids else None,
            "version": current["version"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_department_tree_rejects_cycles_foreign_nodes_and_stale_updates(env):
    admin, other = await organizations(env)
    parent = await department(admin, "营销中心")
    child = await department(admin, "销售部", parent["id"])
    foreign = await department(other, "另一组织")
    path = organization(admin) + "/departments"
    assert (await other.api.get(path)).status_code == 403
    assert (
        await admin.api.post(path, json={"name": "跨组织", "parent_id": foreign["id"]})
    ).status_code == 422
    change = {"name": parent["name"], "version": parent["version"]}
    assert (
        await admin.api.put(path + "/" + parent["id"], json=change | {"parent_id": child["id"]})
    ).status_code == 422
    updated = await admin.api.put(path + "/" + parent["id"], json=change | {"sort_order": 1})
    assert updated.status_code == 200, updated.text
    assert (await admin.api.put(path + "/" + parent["id"], json=change)).status_code == 409
    assert (
        await admin.api.put(
            path + "/" + parent["id"],
            json=change | {"version": updated.json()["version"], "archived": True},
        )
    ).status_code == 409


async def test_workbench_department_scope_and_live_revocation(env, monkeypatch):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    parent = await department(admin, "营销中心")
    child = await department(admin, "销售部", parent["id"])
    sibling = await department(admin, "财务部")
    assignment = await assign(admin, member, [child["id"], sibling["id"]])
    assert assignment["primary_department_id"] == child["id"]
    assert (await member.api.get(organization(admin) + "/departments")).status_code == 403
    uploaded = await admin.api.post(WORKBENCHES, content=package(), headers=BINARY)
    assert uploaded.status_code == 201, uploaded.text
    item = uploaded.json()
    root = f"{WORKBENCHES}/{item['id']}"
    version = item["versions"][0]["id"]
    published = await admin.api.post(
        f"{root}/versions/{version}/publish", json={"revision": item["revision"]}
    )
    assert published.status_code == 200, published.text
    item = published.json()
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    async with native_client(env) as desktop:
        account, _ = await login(env, monkeypatch, desktop, member)
        headers = bearer(await token(desktop, account, "workbenches:config"))
        catalog = "/api/v1/desktop/workbenches"

        async def set_scope(include_descendants):
            return await admin.api.put(
                f"{root}/scope",
                json={
                    "revision": item["revision"],
                    "audience": "selected",
                    "department_grants": [
                        {
                            "department_id": parent["id"],
                            "include_descendants": include_descendants,
                        }
                    ],
                },
            )

        direct = await set_scope(False)
        assert direct.status_code == 200, direct.text
        item = direct.json()
        assert (await desktop.get(catalog, headers=headers)).json()["items"] == []
        inherited = await set_scope(True)
        assert inherited.status_code == 200, inherited.text
        item = inherited.json()
        old = await admin.api.put(
            f"{root}/scope", json={"revision": item["revision"], "audience": "selected"}
        )
        assert old.status_code == 200, old.text
        assert old.json()["department_grants"] == item["department_grants"]
        broad = await admin.api.put(
            f"{root}/scope",
            json={"revision": old.json()["revision"], "audience": "organization"},
        )
        assert broad.status_code == 409
        preview = await admin.api.post(
            organization(admin) + "/departments/scope-preview",
            json={
                "member_ids": [str(member.member.id)],
                "department_grants": item["department_grants"],
            },
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["total"] == 1
        assert preview.json()["items"][0]["department_ids"] == [parent["id"]]
        assert preview.json()["items"][0]["direct"] is True
        assert len((await desktop.get(catalog, headers=headers)).json()["items"]) == 1
        await assign(admin, member, [sibling["id"]])
        assert (await desktop.get(catalog, headers=headers)).json()["items"] == []


async def test_gateway_department_publication_checks_current_member_scope(env, monkeypatch):
    admin, draft, _, _, _ = await gateway_setup(env, monkeypatch)
    member = await env.client(role="member", tenant=admin.tenant)
    parent = await department(admin, "技术中心")
    child = await department(admin, "应用组", parent["id"])
    await assign(admin, member, [child["id"]])
    draft.update(
        audience="selected",
        department_grants=[{"department_id": parent["id"], "include_descendants": True}],
    )
    saved = await admin.api.put(GATEWAY + "/publication", json=draft)
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["department_grants"] == draft["department_grants"]
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    key, _ = await create_key(member)
    async with native_client(env) as client:
        for allowed in (True, False):
            preview = await admin.api.post(
                GATEWAY + "/publication/preview",
                json={"draft": draft, "member_id": str(member.member.id)},
            )
            assert preview.status_code == 200, preview.text
            assert preview.json()["discoverable"] is allowed
            models = await client.get("/api/llm/v1/models", headers=key_headers(key))
            assert models.status_code == 200, models.text
            assert ("team" in {item["id"] for item in models.json()["data"]}) is allowed
            if allowed:
                await assign(admin, member, [])
