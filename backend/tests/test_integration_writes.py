"""Organization applications can push drafts without a member identity."""

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_desktop import native_client
from test_experts import BASE as EXPERTS
from test_experts import content, publish
from test_identity_access import env as env
from test_integrations import APPS, ME, bearer, create_key
from test_mcp import update as update_mcp
from test_mcp import upstream as upstream
from test_skills import package

from app.modules.audit.models import AuditEvent

pytestmark = pytest.mark.asyncio
WRITE = "/api/integrations/v1/write"


@pytest.mark.parametrize("upstream", ["http"], indirect=True)
async def test_push_then_review_and_publish(env, upstream):
    base, _, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, member = await env.client(), await env.client(role="member")
    app = (
        await admin.api.post(
            APPS,
            json={
                "name": "Odoo",
                "mcp_write_enabled": True,
                "skills_write_enabled": True,
                "experts_write_enabled": True,
            },
        )
    ).json()
    key = bearer(await create_key(admin, app, "External"))
    mcp = {
        "name": "Odoo tools",
        "url": url,
        "revision": 0,
        "auth_mode": "personal",
        "credential_fields": [
            {"key": "token", "label": "Odoo API Key", "header": "Authorization", "bearer": True}
        ],
    }
    mcp_source = WRITE + "/mcp/odoo:tools"
    skill_source = WRITE + "/skills/odoo:manual"
    expert_source = WRITE + "/experts/odoo:assistant"
    async with native_client(env) as api:
        me = (await api.get(ME, headers=key)).json()
        assert me["mcp_write_enabled"] and not me["mcp_enabled"]
        assert (
            await api.put(mcp_source, json={**mcp, "enabled": True}, headers=key)
        ).status_code == 422
        pushes = await asyncio.gather(
            api.put(mcp_source, json=mcp, headers=key), api.put(mcp_source, json=mcp, headers=key)
        )
        assert all(r.status_code == 200 for r in pushes), [r.text for r in pushes]
        connector = pushes[0].json()
        assert connector == pushes[1].json() and connector["status"] == "disabled"

        blob = package({"test-skill/references/guide.txt": "Read only"})
        zip_headers = {**key, "Content-Type": "application/zip"}
        args = {"revision": 0, "version": "1.0.0"}
        pushed = await api.put(skill_source, params=args, content=blob, headers=zip_headers)
        assert pushed.status_code == 200, pushed.text
        skill = pushed.json()
        assert skill["status"] == "draft"
        exact = skill["skill_version"]
        r = await api.put(skill_source, params=args, content=blob, headers=zip_headers)
        assert r.json() == skill
        dep = {
            "key": "manual",
            "label": "Manual",
            "skill_id": skill["resource_id"],
            "version_id": exact["id"],
            "sha256": exact["sha256"],
        }
        tool = {
            "key": "odoo",
            "label": "Odoo",
            "connector_id": connector["resource_id"],
            "tools": ["caller"],
        }
        draft = {"revision": 0, "content": content(skills=[dep], connectors=[tool])}
        invalid = await api.put(
            expert_source,
            json={"revision": 0, "content": content(skills=[{**dep, "sha256": "0" * 64}])},
            headers=key,
        )
        assert invalid.status_code == 422 and "manual" in invalid.text
        response = await api.put(expert_source, json=draft, headers=key)
        assert response.status_code == 200, response.text
        expert = response.json()
        assert expert["status"] == "draft" and not expert["dependency_check"]["can_publish"]
        assert {d["key"]: d["status"] for d in expert["dependency_check"]["dependencies"]} == {
            "manual": "version_conflict",
            "odoo": "unavailable",
        }
        expert_path = f"{EXPERTS}/{expert['resource_id']}"
        rejected = await admin.api.post(
            expert_path + "/publish", json={"revision": expert["revision"], "version": "1.0.0"}
        )
        assert rejected.status_code == 409
        skill_path = f"/api/v1/skills/{skill['resource_id']}"
        skill_publish = await admin.api.post(
            f"{skill_path}/versions/{exact['id']}/actions",
            json={"revision": skill["revision"], "action": "publish"},
        )
        assert skill_publish.status_code == 200, skill_publish.text
        current = (await admin.api.get("/api/v1/mcp/services")).json()["items"][0]
        assert current["id"] == connector["resource_id"] and current["auth_mode"] == "personal"
        await update_mcp(admin, current, enabled=True)
        mcp_path = f"/api/v1/mcp/services/{connector['resource_id']}"
        for user, token in [(admin, "person-a"), (member, "person-b")]:
            r = await user.api.put(mcp_path + "/connection", json={"values": {"token": token}})
            assert r.status_code == 200, r.text
            r = await user.api.post(mcp_path + "/discover")
            assert r.status_code == 200, r.text
        policy = await admin.api.put(
            mcp_path + "/policy", json={"kind": "tools", "key": "caller", "enabled": True}
        )
        assert policy.status_code == 200, policy.text
        for user, name in [(admin, "Alice"), (member, "Bob")]:
            call = await user.api.post(mcp_path + "/run", json={"kind": "tools", "key": "caller"})
            assert call.status_code == 200 and name in call.text, call.text
        state = (await api.get(expert_source, headers=key)).json()
        assert state["dependency_check"]["can_publish"]
        published = await publish(admin, {**state, "id": state["resource_id"]})
        changed = await api.put(
            expert_source,
            json={
                "revision": published["revision"],
                "content": content(skills=[dep], connectors=[tool], instructions="New draft"),
            },
            headers=key,
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["status"] == "draft"
        assert changed.json()["current_release_id"] == published["current_release"]["id"]
        retry = await api.put(expert_source, json=draft, headers=key)
        assert retry.status_code == 409 and "source_revision_conflict" in retry.text
        next_skill = await api.put(
            skill_source,
            params={"revision": skill_publish.json()["revision"], "version": "1.1.0"},
            content=package({"test-skill/references/guide.txt": "New draft"}),
            headers=zip_headers,
        )
        assert next_skill.status_code == 200, next_skill.text
        assert next_skill.json()["resource_id"] == skill["resource_id"]
        assert next_skill.json()["current_release_id"] == exact["id"]
        assert next_skill.json()["skill_version"]["version"] == "1.1.0"
        retry = await api.put(skill_source, params=args, content=blob, headers=zip_headers)
        assert retry.json()["skill_version"] == exact
        active = (await api.get(mcp_source, headers=key)).json()
        presentation = await api.put(
            mcp_source,
            json={**mcp, "revision": active["revision"], "description": "采购工具"},
            headers=key,
        )
        assert presentation.status_code == 200, presentation.text
        assert presentation.json()["status"] == "enabled"
        call = await member.api.post(mcp_path + "/run", json={"kind": "tools", "key": "caller"})
        assert call.status_code == 200 and "Bob" in call.text, call.text
        changed_endpoint = await api.put(
            mcp_source,
            json={**mcp, "revision": presentation.json()["revision"], "url": url + "-next"},
            headers=key,
        )
        assert changed_endpoint.status_code == 200, changed_endpoint.text
        assert changed_endpoint.json()["status"] == "disabled"
        check = (await api.get(expert_source, headers=key)).json()["dependency_check"]
        assert not check["can_publish"]

    async with env.sessions() as db:
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.application_id == UUID(app["id"])))
        )
        assert {row.action for row in events} == {
            "mcp.create",
            "mcp.update",
            "skills.import",
            "experts.create",
            "experts.update",
        }
        assert len(events) == 7
        assert all(row.actor_id is None and row.actor_name == "Odoo" for row in events)


async def test_write_grants_and_source_ownership(env):
    admin = await env.client()
    first = (
        await admin.api.post(APPS, json={"name": "Writer", "experts_write_enabled": True})
    ).json()
    second = (
        await admin.api.post(APPS, json={"name": "Other writer", "experts_write_enabled": True})
    ).json()
    first_key = bearer(await create_key(admin, first, "First"))
    second_key = bearer(await create_key(admin, second, "Second"))
    path = WRITE + "/experts/shared-source"
    body = {"revision": 0, "content": content()}
    async with native_client(env) as api:
        assert (
            await api.get(WRITE + "/skills/shared-source", headers=first_key)
        ).status_code == 403
        assert (await api.get(WRITE + "/mcp/shared-source", headers=first_key)).status_code == 403
        one = await api.put(path, headers=first_key, json=body)
        assert one.status_code == 200, one.text
        assert (await api.get(path, headers=second_key)).status_code == 404
        two = await api.put(path, headers=second_key, json=body)
        assert two.status_code == 200, two.text
        assert two.json()["resource_id"] != one.json()["resource_id"]
        hidden_ref = content(
            skills=[
                {
                    "key": "missing",
                    "label": "Missing skill",
                    "skill_id": str(uuid4()),
                    "version_id": str(uuid4()),
                    "sha256": "0" * 64,
                }
            ]
        )
        assert (
            await api.put(path, headers=first_key, json={"revision": 1, "content": hidden_ref})
        ).status_code == 422
        assert (await api.get(path, headers=first_key)).json()["revision"] == 1
        disabled = await admin.api.put(
            f"{APPS}/{first['id']}",
            json={
                **{k: first[k] for k in ("name", "enabled", "version", "models_enabled")},
                "experts_write_enabled": False,
            },
        )
        assert disabled.status_code == 200, disabled.text
        assert (await api.put(path, headers=first_key, json=body)).status_code == 403
        assert (await api.get(path, headers=second_key)).status_code == 200
