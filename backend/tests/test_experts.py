import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from test_desktop_skills import create as create_skill
from test_identity_access import env as env

from app.modules.experts.models import ExpertRecord, ExpertRelease
from app.modules.skills.models import Skill, SkillVersion

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/experts"


def content(**changes):
    return {
        "name": "周报专家",
        "description": "整理工作记录",
        "instructions": "不编造事实。",
        **changes,
    }


async def create(admin, **changes):
    response = await admin.api.post(BASE, json={"content": content(), **changes})
    assert response.status_code == 200, response.text
    return response.json()


async def publish(admin, expert, version="1.0.0"):
    response = await admin.api.post(
        BASE + "/" + expert["id"] + "/publish",
        json={"revision": expert["revision"], "version": version},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_draft_publish_is_immutable_and_scope_independent(env):
    admin = await env.client()
    e = await publish(admin, await create(admin))
    assert e["status"] == "published" and not e["has_changes"]
    old = e["current_release"]
    saved = await admin.api.put(
        BASE + "/" + e["id"],
        json={
            "revision": e["revision"],
            "category": "office",
            "content": content(instructions="新版指令"),
        },
    )
    assert saved.status_code == 200, saved.text
    e = saved.json()
    assert e["has_changes"] and e["current_release"] == old
    duplicate = await admin.api.post(
        BASE + "/" + e["id"] + "/publish", json={"revision": e["revision"], "version": "1.0.0"}
    )
    assert duplicate.status_code == 409
    scoped = await admin.api.put(
        BASE + "/" + e["id"] + "/scope",
        json={"revision": e["revision"], "audience": "organization"},
    )
    assert scoped.status_code == 200
    e = await publish(admin, scoped.json(), "1.1.0")
    assert e["current_release"]["id"] != old["id"]
    async with env.sessions() as db:
        first = await db.get(ExpertRelease, UUID(old["id"]))
        assert first.manifest["instructions"] == "不编造事实。"
        assert first.sha256 == old["sha256"]
    withdrawn = await admin.api.post(
        BASE + "/" + e["id"] + "/withdraw", json={"revision": e["revision"]}
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "withdrawn"
    assert len(withdrawn.json()["releases"]) == 2


async def test_admin_csrf_scope_and_cross_tenant_boundaries(env):
    admin, member = await env.client(), await env.client(role="member")
    e = await create(admin)
    for path in (
        BASE,
        BASE + "/categories",
        BASE + "/" + e["id"],
        BASE + "/dependencies?kind=skills",
    ):
        assert (await member.api.get(path)).status_code == 403
    assert (await member.api.post(BASE, json={"content": content()})).status_code == 403
    assert (
        await admin.api.post(BASE, json={"content": content()}, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    assert (await admin.api.get(BASE + "/" + str(uuid4()))).status_code == 404
    for body in ({"audience": "selected"}, {"audience": "selected", "member_ids": [str(uuid4())]}):
        assert (
            await admin.api.put(
                BASE + "/" + e["id"] + "/scope", json={"revision": e["revision"], **body}
            )
        ).status_code == 422
    admin.api.cookies.clear()
    assert (await admin.api.get(BASE)).status_code == 401


async def test_concurrent_publish_and_stale_save_do_not_overwrite(env):
    admin = await env.client()
    e = await create(admin)
    results = await asyncio.gather(
        *[
            admin.api.post(
                BASE + "/" + e["id"] + "/publish", json={"revision": e["revision"], "version": v}
            )
            for v in ("1.0.0", "2.0.0")
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert (
        await admin.api.put(
            BASE + "/" + e["id"], json={"revision": 1, "content": content(name="覆盖")}
        )
    ).status_code == 409
    async with env.sessions() as db:
        assert len(list(await db.scalars(select(ExpertRelease)))) == 1


async def test_category_rename_move_delete_preserve_release_and_scope(env):
    admin = await env.client()
    r = await admin.api.post(BASE + "/categories", json={"name": "客户支持"})
    assert r.status_code == 200
    c = next(c for c in r.json() if c["name"] == "客户支持")
    e = await publish(admin, await create(admin, category=c["id"]))
    path = BASE + "/categories/" + c["id"]
    r = await admin.api.patch(path, json={"name": "客户服务", "revision": c["revision"]})
    assert r.status_code == 200
    c = next(row for row in r.json() if row["id"] == c["id"])
    changed = (await admin.api.get(BASE + "/" + e["id"])).json()
    assert changed["metadata_revision"] > e["metadata_revision"]
    assert changed["category"]["name"] == "客户服务"
    assert changed["current_release"] == e["current_release"] and not changed["has_changes"]
    r = await admin.api.post(path + "/move", json={"revision": c["revision"], "direction": "up"})
    assert r.status_code == 200 and r.json()[-1]["id"] == "uncategorized"
    c = next(row for row in r.json() if row["id"] == c["id"])
    assert (
        await admin.api.request("DELETE", path, json={"revision": c["revision"], "count": 0})
    ).status_code == 409
    assert (
        await admin.api.request(
            "DELETE", path, json={"revision": c["revision"], "count": 1, "target_id": "general"}
        )
    ).status_code == 200
    changed = (await admin.api.get(BASE + "/" + e["id"])).json()
    assert (
        changed["category"]["id"] == "general"
        and changed["current_release"] == e["current_release"]
    )
    assert changed["audience"] == e["audience"]
    assert (await admin.api.get(BASE + "?category=" + c["id"])).status_code == 422
    assert (
        await admin.api.request(
            "DELETE", BASE + "/categories/uncategorized", json={"revision": 1, "count": 0}
        )
    ).status_code == 409


async def test_locked_skill_version_and_permission_gap(env):
    admin, member = await env.client(), await env.client(role="member")
    skill, _ = await create_skill(admin, audience="selected", member_ids=[str(member.member.id)])
    version = skill["versions"][0]
    ref = {
        "key": "report",
        "label": "周报技能",
        "required": True,
        "load": "always",
        "skill_id": skill["id"],
        "version_id": version["id"],
        "sha256": version["sha256"],
    }
    e = await create(admin, content=content(skills=[ref]))
    assert e["check"]["can_publish"]
    assert e["check"]["dependencies"][0]["missing_members"] == 1
    e = await publish(admin, e)
    async with env.sessions() as db:
        v = await db.get(SkillVersion, UUID(version["id"]))
        v.status = "withdrawn"
        s = await db.get(Skill, UUID(skill["id"]))
        s.default_version_id = None
        await db.commit()
    current = (await admin.api.get(BASE + "/" + e["id"])).json()
    assert current["check"]["dependencies"][0]["status"] == "version_conflict"
    assert not current["check"]["can_publish"]
    assert (
        await admin.api.post(
            BASE + "/" + e["id"] + "/publish",
            json={"revision": current["revision"], "version": "1.1.0"},
        )
    ).status_code == 409
    # Existing stale reference can remain while editing unrelated draft fields.
    assert (
        await admin.api.put(
            BASE + "/" + e["id"],
            json={"revision": current["revision"], "content": content(skills=[ref], name="新名称")},
        )
    ).status_code == 200


@pytest.mark.parametrize(
    "changes",
    [
        {"tags": ["x"] * 9},
        {"instructions": "x" * 64001},
        {"name": "\0bad"},
        {"name": "😀" * 41},
        {"avatar": "https://example.com/a.png"},
        {
            "skills": [
                {
                    "key": "__proto__",
                    "label": "x",
                    "required": True,
                    "skill_id": str(uuid4()),
                    "version_id": str(uuid4()),
                    "sha256": "a" * 64,
                }
            ]
        },
    ],
)
async def test_manifest_limits_and_unsafe_keys_rejected(env, changes):
    admin = await env.client()
    assert (await admin.api.post(BASE, json={"content": content(**changes)})).status_code == 422


async def test_category_uniqueness_search_and_missing_instructions(env):
    admin = await env.client()
    assert (
        await admin.api.post(BASE + "/categories", json={"name": " Office "})
    ).status_code == 200
    assert (await admin.api.post(BASE + "/categories", json={"name": "office"})).status_code == 409
    e = await create(admin, content=content(instructions=""))
    assert not e["check"]["can_publish"]
    assert (await admin.api.get(BASE + "?q=%25")).json()["total"] == 0
    async with env.sessions() as db:
        assert (await db.get(ExpertRecord, UUID(e["id"]))).audience == "administrators"


async def test_skill_update_impact_and_refresh_only_change_draft(env):
    from test_skills import action, payload

    admin = await env.client()
    skill, _ = await create_skill(admin)
    version = skill["versions"][0]
    ref = {
        "key": "report",
        "label": "周报技能",
        "required": True,
        "load": "always",
        "skill_id": skill["id"],
        "version_id": version["id"],
        "sha256": version["sha256"],
    }
    expert = await publish(admin, await create(admin, content=content(skills=[ref])))
    imported = await admin.api.post(
        "/api/v1/skills/import",
        json={
            **payload(),
            "skill_id": skill["id"],
            "revision": skill["revision"],
            "version": "2.0.0",
        },
    )
    assert imported.status_code == 200, imported.text
    newer = imported.json()
    target = newer["versions"][0]
    impact = await admin.api.get(
        BASE + "/skill-impact", params={"skill_id": skill["id"], "target_version_id": target["id"]}
    )
    assert impact.json()["total"] == 1
    assert (await action(admin, newer, "publish")).status_code == 200
    refreshed = await admin.api.post(
        BASE + "/" + expert["id"] + "/refresh-skills", json={"revision": expert["revision"]}
    )
    assert refreshed.status_code == 200, refreshed.text
    result = refreshed.json()
    assert result["content"]["skills"][0]["version_id"] == target["id"]
    assert result["current_release"] == expert["current_release"]
    assert result["has_changes"] and result["check"]["can_publish"]
    assert result["dependency_issues"] == 0  # superseded exact reference stays usable
    assert result["check"]["dependencies"][0]["update_available"] is False
    published = await publish(admin, result, "2.0.0")
    assert published["dependency_issues"] == 0


async def test_migration_seeds_categories_and_preserves_existing_skill_data(env):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.modules.experts.models import ExpertCategoryRecord
    from app.modules.skills.models import SkillPackage

    admin = await env.client()
    skill, blob = await create_skill(admin)
    migration = importlib.import_module("migrations.versions.93n_experts")
    async with env.sessions() as db:
        connection = await db.connection()

        def upgrade(sync):
            for table in (
                ExpertRelease.__table__,
                ExpertRecord.__table__,
                ExpertCategoryRecord.__table__,
            ):
                table.drop(sync)
            with Operations.context(MigrationContext.configure(sync)):
                migration.upgrade()

        await connection.run_sync(upgrade)
        await db.commit()
        rows = list(await db.scalars(select(ExpertCategoryRecord)))
        assert len(rows) == 9 and rows[-1].id == "uncategorized"
        assert (await db.get(SkillPackage, UUID(skill["default_version_id"]))).data == blob


@pytest.mark.parametrize("published", [False, True])
async def test_delete_removes_only_own_expert_and_retains_audit(env, published):
    from test_mcp import create as create_connector
    from test_mcp import update as update_connector

    from app.modules.audit.models import AuditEvent
    from app.modules.mcp.models import McpService

    admin, member = await env.client(), await env.client(role="member")
    skill, _ = await create_skill(admin)
    version = skill["versions"][0]
    connector = await create_connector(admin)
    connector = await update_connector(admin, connector, enabled=True)
    e = await create(
        admin,
        content=content(
            skills=[
                {
                    "key": "skill",
                    "label": "技能",
                    "skill_id": skill["id"],
                    "version_id": version["id"],
                    "sha256": version["sha256"],
                }
            ],
            connectors=[{"key": "mcp", "label": "连接器", "connector_id": connector["id"]}],
        ),
    )
    if published:
        e = await publish(admin, e)
        e = await publish(admin, e, "2.0.0")
    other = await create(admin)
    path = BASE + "/" + e["id"]
    assert (
        await member.api.request("DELETE", path, json={"revision": e["revision"]})
    ).status_code == 403
    assert (
        await admin.api.request(
            "DELETE", path, json={"revision": e["revision"]}, headers={"x-csrf-token": "bad"}
        )
    ).status_code == 403
    assert (
        await admin.api.request("DELETE", path, json={"revision": e["revision"] + 1})
    ).status_code == 409
    assert (await admin.api.get(path)).status_code == 200
    assert (
        await admin.api.request("DELETE", path, json={"revision": e["revision"]})
    ).status_code == 200
    assert (await admin.api.get(path)).status_code == 404
    assert (
        await admin.api.request("DELETE", path, json={"revision": e["revision"]})
    ).status_code == 404
    assert [v["id"] for v in (await admin.api.get(BASE)).json()["items"]] == [other["id"]]
    async with env.sessions() as db:
        assert await db.get(ExpertRecord, UUID(e["id"])) is None
        assert not list(
            await db.scalars(select(ExpertRelease).where(ExpertRelease.expert_id == UUID(e["id"])))
        )
        assert await db.get(Skill, UUID(skill["id"])) is not None
        assert await db.get(SkillVersion, UUID(version["id"])) is not None
        assert await db.get(McpService, UUID(connector["id"])) is not None
        logs = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "experts.delete"))
        )
        assert len(logs) == 1


async def test_concurrent_delete_blocks_stale_publish(env):
    admin = await env.client()
    e = await create(admin)
    path = BASE + "/" + e["id"]
    deleted, published = await asyncio.gather(
        admin.api.request("DELETE", path, json={"revision": e["revision"]}),
        admin.api.post(path + "/publish", json={"revision": e["revision"], "version": "1.0.0"}),
    )
    assert (deleted.status_code, published.status_code) in {(200, 404), (409, 200)}
    async with env.sessions() as db:
        remaining = await db.get(ExpertRecord, UUID(e["id"]))
        releases = list(
            await db.scalars(select(ExpertRelease).where(ExpertRelease.expert_id == UUID(e["id"])))
        )
        assert (remaining is not None) == (published.status_code == 200)
        assert len(releases) == int(published.status_code == 200)
