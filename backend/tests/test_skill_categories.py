"""Real PostgreSQL category management, atomic migration and desktop compatibility."""

import asyncio
import importlib
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select
from test_desktop import native_client
from test_desktop_skills import create, download_input, native
from test_identity_access import env as identity_env

from app.modules.audit.models import AuditEvent
from app.modules.desktop.oidc import NativeIdentity
from app.modules.skills.models import Skill, SkillCategoryRecord, SkillPackage

pytestmark = pytest.mark.asyncio
env = identity_env
BASE = "/api/v1/skills/categories"


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


async def choices(admin):
    response = await admin.api.get(BASE)
    assert response.status_code == 200, response.text
    return response.json()


async def add(admin, name):
    response = await admin.api.post(BASE, json={"name": name})
    assert response.status_code == 200, response.text
    return next(c for c in response.json() if c["name"] == name.strip())


async def remove(admin, category, **changes):
    return await admin.api.request(
        "DELETE",
        BASE + "/" + category["id"],
        json={
            "revision": category["revision"],
            "count": category["count"],
            "target_id": "uncategorized",
            **changes,
        },
    )


async def test_dynamic_category_rename_reorder_and_dsh_contract(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    category = await add(admin, " 客户支持 ")
    skill, blob = await create(admin, category=category["id"])
    assert skill["category_name"] == "客户支持"
    async with native_client(env) as api:
        _, headers = await native(env, monkeypatch, api, member)
        detail_path = "/api/v1/desktop/skills/" + skill["id"]
        detail = (await api.get(detail_path, headers=headers)).json()
        assert detail["category"] == {"id": category["id"], "name": "客户支持"}
        proof = download_input(detail)
        renamed = await admin.api.patch(
            BASE + "/" + category["id"], json={"name": "客户服务", "revision": 1}
        )
        assert renamed.status_code == 200
        current = next(c for c in renamed.json() if c["id"] == category["id"])
        assert current["count"] == 1
        moved = await admin.api.post(
            BASE + "/" + category["id"] + "/move",
            json={"direction": "up", "revision": current["revision"]},
        )
        assert moved.status_code == 200
        ids = [c["id"] for c in moved.json()]
        assert ids[-1] == "uncategorized" and ids.index(category["id"]) < ids.index("other")
        desktop = (await api.get("/api/v1/desktop/skills/categories", headers=headers)).json()
        assert [c["id"] for c in desktop] == ids
        assert next(c for c in desktop if c["id"] == category["id"]) == {
            "id": category["id"],
            "name": "客户服务",
            "count": 1,
        }
        updated = (
            await api.post(
                "/api/v1/desktop/skills/check-updates",
                headers=headers,
                json={"items": [{"skill_id": skill["id"], **proof}]},
            )
        ).json()["items"][0]
        assert updated["status"] == "current" and updated["skill"]["category"]["name"] == "客户服务"
        assert (
            await api.post(detail_path + "/download", headers=headers, json=proof)
        ).content == blob


async def test_delete_migrates_all_versions_and_preserves_scope_and_bytes(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    category = await add(admin, "待迁移")
    target = await add(admin, "目标类别")
    skill, blob = await create(
        admin, category=category["id"], audience="selected", member_ids=[str(member.member.id)]
    )
    draft, _ = await create(admin, "draft-example", category=category["id"], publish=False)
    assert (await remove(admin, category)).status_code == 409  # stale count
    category = next(c for c in await choices(admin) if c["id"] == category["id"])
    assert category["count"] == 2
    for invalid in (category["id"], "does-not-exist"):
        assert (await remove(admin, category, target_id=invalid)).status_code == 422
    assert (await remove(admin, category, target_id=target["id"])).status_code == 200
    for original in (skill, draft):
        current = (await admin.api.get("/api/v1/skills/" + original["id"])).json()
        assert current["category"] == target["id"] and current["category_name"] == "目标类别"
        for key in ("audience", "member_ids", "versions", "default_version_id"):
            assert current[key] == original[key]
        assert current["revision"] == original["revision"] + 1
    async with native_client(env) as api:
        _, headers = await native(env, monkeypatch, api, member)
        counts = (await api.get("/api/v1/desktop/skills/categories", headers=headers)).json()
        assert next(c for c in counts if c["id"] == target["id"])["count"] == 1
        assert category["id"] not in [c["id"] for c in counts]
    async with env.sessions() as db:
        assert (await db.get(SkillPackage, UUID(skill["default_version_id"]))).data == blob
        event = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "skills.category.delete")
        )
        assert event.details["skill_count"] == "2"
    assert (await admin.api.get("/api/v1/skills?category=" + category["id"])).status_code == 422


async def test_category_permission_validation_and_system_protection(env):
    admin, member = await env.client(), await env.client(role="member")
    category = await add(admin, "Support")
    assert (await member.api.get(BASE)).status_code == 403
    for who, headers in ((member, {}), (admin, {"x-csrf-token": "wrong"})):
        for method, path, body in (
            ("POST", BASE, {"name": "Unauthorized"}),
            ("PATCH", BASE + "/" + category["id"], {"name": "Unauthorized", "revision": 1}),
            ("POST", BASE + "/" + category["id"] + "/move", {"direction": "up", "revision": 1}),
            ("DELETE", BASE + "/" + category["id"], {"revision": 1, "count": 0}),
        ):
            assert (
                await who.api.request(method, path, json=body, headers=headers)
            ).status_code == 403
    for name in (" ", "a" * 31):
        assert (await admin.api.post(BASE, json={"name": name})).status_code == 422
    assert (await admin.api.post(BASE, json={"name": " support "})).status_code == 409
    system = next(c for c in await choices(admin) if c["system"])
    assert (await remove(admin, system)).status_code == 409
    assert (
        await admin.api.patch(BASE + "/uncategorized", json={"name": "New", "revision": 1})
    ).status_code == 409
    assert (
        await admin.api.post(BASE + "/uncategorized/move", json={"direction": "up", "revision": 1})
    ).status_code == 409
    assert (await remove(admin, category)).status_code == 200
    assert not any(
        c["id"] == category["id"] for c in await choices(admin)
    )  # defaults not re-seeded


async def test_concurrent_duplicate_rename_and_delete_assignment_are_serialized(env):
    admin = await env.client()
    results = await asyncio.gather(
        *[admin.api.post(BASE, json={"name": "Concurrent"}) for _ in range(2)]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    category = next(c for c in await choices(admin) if c["name"] == "Concurrent")
    results = await asyncio.gather(
        *[
            admin.api.patch(BASE + "/" + category["id"], json={"name": name, "revision": 1})
            for name in ("A", "B")
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    category = next(c for c in await choices(admin) if c["id"] == category["id"])
    skill, _ = await create(admin)
    values = {
        k: skill[k] for k in ("display_name", "description", "audience", "member_ids", "revision")
    }
    deleted, assigned = await asyncio.gather(
        remove(admin, category),
        admin.api.put("/api/v1/skills/" + skill["id"], json={**values, "category": category["id"]}),
    )
    assert (deleted.status_code, assigned.status_code) in ((200, 422), (409, 200))
    async with env.sessions() as db:
        current = await db.get(Skill, UUID(skill["id"]))
        assert await db.get(SkillCategoryRecord, (admin.tenant.id, current.category))


async def test_category_migration_preserves_existing_ids_packages_and_publication(env):
    admin = await env.client()
    skill, blob = await create(admin, category="design")
    migration = importlib.import_module("migrations.versions.79j_skill_categories")
    async with env.sessions() as db:
        conn = await db.connection()

        def cycle(sync):
            with Operations.context(MigrationContext.configure(sync)):
                migration.downgrade()
                migration.upgrade()

        await conn.run_sync(cycle)
        current = await db.get(Skill, UUID(skill["id"]))
        assert current.category == "design" and current.category_info.name == "设计创意"
        assert str(current.default_version_id) == skill["default_version_id"]
        assert (await db.get(SkillPackage, current.default_version_id)).data == blob
