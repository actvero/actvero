"""Exact historical qualification stays subordinate to current resource permissions."""

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_desktop import bearer, login, native_client
from test_desktop_mcp import token
from test_desktop_skills import create as create_skill
from test_experts import content, create, publish
from test_identity_access import env as identity_env
from test_skills import action, package, payload

from app.modules.desktop.models import ResourceAdoption
from app.modules.desktop.oidc import NativeIdentity
from app.modules.skills.models import Skill

env = identity_env
pytestmark = pytest.mark.asyncio
SKILLS = "/api/v1/desktop/skills"
EXPERTS = "/api/v1/desktop/experts"


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


async def replace(admin, skill):
    data = package(markdown="---\nname: test-skill\ndescription: New\n---\n# New instructions")
    response = await admin.api.post(
        "/api/v1/skills/import",
        json={
            **payload(data=data),
            "skill_id": skill["id"],
            "revision": skill["revision"],
            "version": "2.0.0",
        },
    )
    assert response.status_code == 200, response.text
    second = response.json()
    second = (await action(admin, second, "publish", second["versions"][0]["id"])).json()
    return second


def chosen(skill):
    version = next(v for v in skill["versions"] if v["id"] == skill["default_version_id"])
    return {"version_id": version["id"], "sha256": version["sha256"], "access_version": 2}


async def resource(api, root, name):
    return bearer(await token(api, root, name + ":catalog"))


async def test_explicit_adoption_is_idempotent_cross_device_and_requires_live_scope(
    env, monkeypatch
):
    admin, member, stranger = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    skill, original = await create_skill(admin, audience="organization")
    proof = chosen(skill)
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, member)
        headers = await resource(api, root, "skills")
        body = {**proof, "request_id": str(uuid4())}
        receipts = await asyncio.gather(
            *[
                api.post(SKILLS + "/" + skill["id"] + "/adopt", headers=headers, json=body)
                for _ in range(3)
            ]
        )
        assert all(r.status_code == 200 for r in receipts)
        assert len({r.json()["id"] for r in receipts}) == 1
        async with env.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(ResourceAdoption)) == 1
        second = await replace(admin, skill)
        assert (
            await api.post(
                SKILLS + "/" + skill["id"] + "/download",
                headers=headers,
                json={k: v for k, v in proof.items() if k != "access_version"},
            )
        ).status_code == 409
        root2, _ = await login(env, monkeypatch, api, member)
        headers2 = await resource(api, root2, "skills")
        downloaded = await api.post(
            SKILLS + "/" + skill["id"] + "/download", headers=headers2, json=proof
        )
        assert downloaded.status_code == 200 and downloaded.content == original
        updates = (
            await api.post(
                SKILLS + "/check-updates",
                headers=headers2,
                json={"access_version": 2, "items": [{**proof, "skill_id": skill["id"]}]},
            )
        ).json()["items"][0]
        assert updates["status"] == "update_available" and updates["adopted_usable"]
        assert updates["adopted_state"] == "superseded" and updates["update_available"]
        detail = await api.get(
            SKILLS + "/" + skill["id"],
            headers=headers2,
            params={"access_version": 2, "version_id": proof["version_id"]},
        )
        assert detail.status_code == 200
        assert detail.json()["current_version"]["id"] == proof["version_id"]
        assert detail.json()["recommended_version"]["id"] == second["default_version_id"]
        assert detail.json()["version_state"] == "superseded" and detail.json()["update_available"]
        legacy = await api.get(SKILLS + "/" + skill["id"], headers=headers2)
        assert "recommended_version" not in legacy.json()
        assert legacy.json()["current_version"]["id"] == second["default_version_id"]
        conflict = await api.post(
            SKILLS + "/" + skill["id"] + "/adopt",
            headers=headers2,
            json={**chosen(second), "request_id": body["request_id"]},
        )
        assert conflict.status_code == 409
        root3, _ = await login(env, monkeypatch, api, stranger)
        h3 = await resource(api, root3, "skills")
        assert (
            await api.post(SKILLS + "/" + skill["id"] + "/download", headers=h3, json=proof)
        ).status_code == 404
        async with env.sessions() as db:
            row = await db.get(Skill, UUID(skill["id"]))
            row.audience = "selected"
            row.member_ids = [str(stranger.member.id)]
            await db.commit()
        assert (
            await api.post(SKILLS + "/" + skill["id"] + "/download", headers=headers2, json=proof)
        ).status_code == 404
        assert (await api.get("/api/v1/desktop/me", headers=bearer(root2))).status_code == 200


async def test_explicit_withdraw_old_version_does_not_withdraw_new_but_blocks_history(
    env, monkeypatch
):
    admin = await env.client()
    skill, _ = await create_skill(admin)
    proof = chosen(skill)
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, admin)
        headers = await resource(api, root, "skills")
        assert (
            await api.post(
                SKILLS + "/" + skill["id"] + "/adopt",
                headers=headers,
                json={**proof, "request_id": str(uuid4())},
            )
        ).status_code == 200
        second = await replace(admin, skill)
        blocked = await action(admin, second, "withdraw", proof["version_id"])
        assert (
            blocked.status_code == 200
            and blocked.json()["default_version_id"] == second["default_version_id"]
        )
        assert (
            await api.post(SKILLS + "/" + skill["id"] + "/download", headers=headers, json=proof)
        ).status_code == 404
        assert (
            await api.post(
                SKILLS + "/" + skill["id"] + "/download", headers=headers, json=chosen(second)
            )
        ).status_code == 200


async def test_current_expert_exact_reference_and_adopted_old_release_keep_skill_version(
    env, monkeypatch
):
    admin, member, newcomer = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    skill, original = await create_skill(admin, audience="organization")
    proof = chosen(skill)
    manifest = content(
        skills=[
            {
                "key": "notes",
                "label": "Notes",
                "required": True,
                "skill_id": skill["id"],
                "version_id": proof["version_id"],
                "sha256": proof["sha256"],
            }
        ]
    )
    expert = await create(admin, content=manifest)
    scoped = await admin.api.put(
        "/api/v1/experts/" + expert["id"] + "/scope",
        json={"revision": expert["revision"], "audience": "organization"},
    )
    expert = await publish(admin, scoped.json())
    release = expert["current_release"]
    eproof = {"access_version": 2, "release_id": release["id"], "sha256": release["sha256"]}
    async with native_client(env) as api:
        root, _ = await login(env, monkeypatch, api, member)
        eh = await resource(api, root, "experts")
        sh = await resource(api, root, "skills")
        assert (
            await api.post(
                EXPERTS + "/" + expert["id"] + "/adopt",
                headers=eh,
                json={**eproof, "request_id": str(uuid4())},
            )
        ).status_code == 200
        await replace(admin, skill)
        state = await api.post(EXPERTS + "/" + expert["id"] + "/resolve", headers=eh, json=eproof)
        assert state.status_code == 200 and state.json()["can_prepare"]
        dependency = state.json()["dependencies"][0]
        assert (
            dependency["version_id"] == proof["version_id"]
            and dependency["version_state"] == "superseded"
        )
        assert dependency["update_available"]
        v3 = await api.post(
            EXPERTS + "/" + expert["id"] + "/resolve",
            headers=eh,
            json={**eproof, "access_version": 3},
        )
        assert v3.status_code == 200 and v3.json()["can_prepare"]
        assert v3.json()["dependencies"][0]["version_state"] == "superseded"
        assert v3.json()["dependencies"][0]["version_id"] == proof["version_id"]
        from_expert = {**proof, "expert_id": expert["id"], "expert_release_id": release["id"]}
        old = await api.post(SKILLS + "/" + skill["id"] + "/download", headers=sh, json=from_expert)
        assert old.content == original
        async with env.sessions() as db:
            assert (
                await db.scalar(select(func.count()).select_from(ResourceAdoption)) == 1
            )  # Read-only resolve never adopts dependencies.
        latest = (await admin.api.get("/api/v1/experts/" + expert["id"])).json()
        assert (
            latest["check"]["can_publish"]
            and latest["check"]["dependencies"][0]["update_available"]
        )
        saved = await admin.api.put(
            "/api/v1/experts/" + expert["id"],
            json={
                "revision": latest["revision"],
                "content": {**manifest, "instructions": "New expert text"},
            },
        )
        assert saved.status_code == 200
        updated = await publish(admin, saved.json(), "2.0.0")
        locked = await api.post(EXPERTS + "/" + expert["id"] + "/resolve", headers=eh, json=eproof)
        assert (
            locked.status_code == 200
            and locked.json()["can_prepare"]
            and locked.json()["update_available"]
        )
        assert locked.json()["dependencies"][0]["version_id"] == proof["version_id"]
        newer = (
            await api.post(
                EXPERTS + "/check-updates",
                headers=eh,
                json={"access_version": 2, "items": [{**eproof, "expert_id": expert["id"]}]},
            )
        ).json()["items"][0]
        assert newer["adopted_usable"] and newer["update_available"]
        legacy_updates = await api.post(
            EXPERTS + "/check-updates",
            headers=eh,
            json={
                "items": [
                    {
                        "expert_id": str(uuid4()),
                        "release_id": release["id"],
                        "sha256": release["sha256"],
                    }
                ]
            },
        )
        assert legacy_updates.json()["items"][0]["expert"] is None
        assert "adopted_usable" not in legacy_updates.json()["items"][0]
        fresh_root, _ = await login(env, monkeypatch, api, newcomer)
        fresh_h = await resource(api, fresh_root, "experts")
        assert (
            await api.post(EXPERTS + "/" + expert["id"] + "/resolve", headers=fresh_h, json=eproof)
        ).status_code == 404
        blocked = await admin.api.post(
            "/api/v1/experts/" + expert["id"] + "/withdraw", json={"revision": updated["revision"]}
        )
        assert blocked.status_code == 200
        assert (
            await api.post(EXPERTS + "/" + expert["id"] + "/resolve", headers=eh, json=eproof)
        ).status_code == 404
        assert (
            await api.post(SKILLS + "/" + skill["id"] + "/download", headers=sh, json=from_expert)
        ).status_code == 404
