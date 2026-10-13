"""Selected updates are atomic, exact, permission-scoped and independently recoverable."""

import asyncio
import base64
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_desktop_skills import create as skill_create
from test_experts import BASE, content, create, publish
from test_identity_access import env as env
from test_skills import payload

from app.modules.audit.models import AuditEvent
from app.modules.experts.models import DependencyCommandReceipt, ExpertRecord, ExpertRelease

pytestmark = pytest.mark.asyncio


def ref(skill, key="report"):
    version = next(v for v in skill["versions"] if v["id"] == skill["default_version_id"])
    return dict(
        key=key,
        label=key,
        required=True,
        load="always",
        skill_id=skill["id"],
        version_id=version["id"],
        sha256=version["sha256"],
    )


async def newer(admin, skill, blob, version="2.0.0"):
    response = await admin.api.post(
        "/api/v1/skills/import",
        json={
            **payload(),
            "package_base64": base64.b64encode(blob).decode(),
            "skill_id": skill["id"],
            "revision": skill["revision"],
            "version": version,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()
    return result, next(v for v in result["versions"] if v["version"] == version)


def selection(expert, target, key="report"):
    original = next(r for r in expert["content"]["skills"] if r["key"] == key)
    return dict(
        expert_id=expert["id"],
        revision=expert["revision"],
        changes=[
            dict(
                key=key,
                from_version_id=original["version_id"],
                from_sha256=original["sha256"],
                to_version_id=target["id"],
                to_sha256=target["sha256"],
            )
        ],
    )


async def action(admin, skill, target, selections, request=None):
    request = request or str(uuid4())
    body = dict(
        action="publish", revision=skill["revision"], request_id=request, draft_updates=selections
    )
    path = f"/api/v1/skills/{skill['id']}/versions/{target['id']}/actions"
    return await admin.api.post(path, json=body), path, body


async def test_publish_updates_only_selected_draft_and_preserves_release(env):
    admin = await env.client()
    skill, blob = await skill_create(admin)
    selected = await publish(admin, await create(admin, content=content(skills=[ref(skill)])))
    other = await create(admin, content=content(skills=[ref(skill)]))
    old_release = selected["current_release"]
    skill, target = await newer(admin, skill, blob)
    result, path, body = await action(admin, skill, target, [selection(selected, target)])
    assert result.status_code == 200, result.text
    changed = (await admin.api.get(BASE + "/" + selected["id"])).json()
    assert changed["revision"] == selected["revision"] + 1
    assert changed["content"]["skills"][0]["version_id"] == target["id"]
    assert changed["current_release"] == old_release and changed["has_changes"]
    assert changed["content"]["instructions"] == selected["content"]["instructions"]
    untouched = (await admin.api.get(BASE + "/" + other["id"])).json()
    assert all(
        untouched[k] == other[k] for k in ("content", "revision", "current_release", "releases")
    )
    repeated = await admin.api.post(path, json=body)
    assert repeated.status_code == 200
    receipt = await admin.api.get(BASE + "/dependency-commands/" + body["request_id"])
    assert receipt.status_code == 200
    assert receipt.json()["updated_experts"] == [
        {"expert_id": selected["id"], "revision": changed["revision"]}
    ]
    assert (await admin.api.post(path, json={**body, "draft_updates": []})).status_code == 409
    async with env.sessions() as db:
        release = await db.get(ExpertRelease, UUID(old_release["id"]))
        assert release.sha256 == old_release["sha256"]
        assert (
            release.dependency_refs["skills"][0]["version_id"]
            == selected["content"]["skills"][0]["version_id"]
        )
        assert await db.scalar(select(func.count()).select_from(DependencyCommandReceipt)) == 1


async def test_stale_second_expert_rolls_back_entire_publish(env):
    admin = await env.client()
    skill, blob = await skill_create(admin)
    first = await create(admin, content=content(skills=[ref(skill)]))
    second = await create(admin, content=content(skills=[ref(skill)]))
    skill, target = await newer(admin, skill, blob)
    choices = [selection(first, target), selection(second, target)]
    changed = await admin.api.put(
        BASE + "/" + second["id"],
        json={
            "revision": second["revision"],
            "content": {**second["content"], "instructions": "其他人的编辑"},
        },
    )
    assert changed.status_code == 200
    result, _, body = await action(admin, skill, target, choices)
    assert result.status_code == 409
    assert (await admin.api.get(BASE + "/" + first["id"])).json() == first
    current = (await admin.api.get("/api/v1/skills/" + skill["id"])).json()
    assert (
        current["revision"] == skill["revision"]
        and current["default_version_id"] == skill["default_version_id"]
    )
    assert next(v for v in current["versions"] if v["id"] == target["id"])["status"] == "draft"
    assert (
        await admin.api.get(BASE + "/dependency-commands/" + body["request_id"])
    ).status_code == 404


async def test_same_command_concurrency_single_mutation(env):
    admin = await env.client()
    skill, blob = await skill_create(admin)
    expert = await create(admin, content=content(skills=[ref(skill)]))
    skill, target = await newer(admin, skill, blob)
    body = dict(
        action="publish",
        revision=skill["revision"],
        request_id=str(uuid4()),
        draft_updates=[selection(expert, target)],
    )
    path = f"/api/v1/skills/{skill['id']}/versions/{target['id']}/actions"
    results = await asyncio.gather(*[admin.api.post(path, json=body) for _ in range(2)])
    assert [r.status_code for r in results] == [200, 200]
    async with env.sessions() as db:
        e = await db.get(ExpertRecord, UUID(expert["id"]))
        assert e.revision == expert["revision"] + 1
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "experts.refresh_skills")
            )
            == 1
        )


async def test_paginated_impact_includes_unpublished_and_exact_source(env):
    admin = await env.client()
    skill, blob = await skill_create(admin)
    old_ref = ref(skill)
    for i in range(23):
        await create(admin, content=content(name=f"专家 {i:02}", skills=[old_ref]))
    skill, target = await newer(admin, skill, blob)
    base = BASE + f"/skill-impact?skill_id={skill['id']}&target_version_id={target['id']}"
    first = (await admin.api.get(base)).json()
    second = (await admin.api.get(base + "&page=2")).json()
    assert first["total"] == 23 and len(first["items"]) == 20 and len(second["items"]) == 3
    assert not {e["id"] for e in first["items"]} & {e["id"] for e in second["items"]}
    assert first["items"][0]["version"] == "未发布"
    assert first["items"][0]["draft_changes"][0]["to_version_id"] == target["id"]
    assert (await admin.api.get(base + "&q=专家%2002")).json()["total"] == 1
    assert (await admin.api.get(base + "&source_version_id=" + target["id"])).json()["total"] == 0
    assert (await admin.api.get(base + "&page=0")).status_code == 422
    assert (await admin.api.get(base + "&target_version_id=" + str(uuid4()))).status_code == 422


@pytest.mark.parametrize(
    "bad", ["from_id", "from_sha", "to_sha", "other_skill", "empty", "duplicate"]
)
async def test_exact_selection_validation_never_changes_drafts(env, bad):
    admin = await env.client()
    skill, blob = await skill_create(admin)
    expert = await create(admin, content=content(skills=[ref(skill)]))
    skill, target = await newer(admin, skill, blob)
    choice = selection(expert, target)
    change = choice["changes"][0]
    if bad == "from_id":
        change["from_version_id"] = str(uuid4())
    if bad == "from_sha":
        change["from_sha256"] = "0" * 64
    if bad == "to_sha":
        change["to_sha256"] = "0" * 64
    if bad == "other_skill":
        other, _ = await skill_create(admin, "other-skill")
        change["to_version_id"] = other["default_version_id"]
    if bad == "empty":
        choice["changes"] = []
    if bad == "duplicate":
        choice["changes"].append(change.copy())
    response, _, _ = await action(admin, skill, target, [choice])
    assert response.status_code in [409, 422], response.text
    assert (await admin.api.get(BASE + "/" + expert["id"])).json() == expert


async def test_independent_refresh_selected_only_and_target_preview_conflict(env):
    admin = await env.client()
    skill, blob = await skill_create(admin)
    second_skill, second_blob = await skill_create(admin, "second-skill")
    expert = await publish(
        admin,
        await create(admin, content=content(skills=[ref(skill, "a"), ref(second_skill, "b")])),
    )
    skill, target = await newer(admin, skill, blob)
    published, _, _ = await action(admin, skill, target, [])
    assert published.status_code == 200
    body = dict(
        revision=expert["revision"],
        request_id=str(uuid4()),
        changes=selection(expert, target, "a")["changes"],
    )
    path = BASE + "/" + expert["id"] + "/refresh-skills"
    response = await admin.api.post(path, json=body)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["content"]["skills"][0]["version_id"] == target["id"]
    assert updated["content"]["skills"][1] == expert["content"]["skills"][1]
    assert updated["current_release"] == expert["current_release"]
    assert (await admin.api.post(path, json=body)).status_code == 200
    second_skill, target_b = await newer(admin, second_skill, second_blob)
    second_published, _, _ = await action(admin, second_skill, target_b, [])
    assert second_published.status_code == 200
    obsolete = dict(
        revision=updated["revision"],
        request_id=str(uuid4()),
        changes=selection(updated, target_b, "b")["changes"],
    )
    second_skill, third = await newer(admin, second_published.json(), second_blob, "3.0.0")
    assert (await action(admin, second_skill, third, []))[0].status_code == 200
    assert (await admin.api.post(path, json=obsolete)).status_code == 409
    assert (await admin.api.get(BASE + "/" + expert["id"])).json()["content"] == updated["content"]


async def test_receipts_are_own_admin_and_live_permissions(env):
    admin, other, member = await env.client(), await env.client(), await env.client(role="member")
    skill, blob = await skill_create(admin)
    skill, target = await newer(admin, skill, blob)
    response, path, body = await action(admin, skill, target, [])
    assert response.status_code == 200
    receipt = BASE + "/dependency-commands/" + body["request_id"]
    assert (await other.api.get(receipt)).status_code == 404
    assert (await member.api.get(receipt)).status_code == 403
    assert (await member.api.get(BASE + "/skill-impact?skill_id=" + skill["id"])).status_code == 403
    async with env.sessions() as db:
        from app.modules.members.models import Membership

        row = await db.get(Membership, admin.member.id)
        row.role = "member"
        await db.commit()
    assert (await admin.api.get(receipt)).status_code == 403
    assert (await admin.api.post(path, json=body)).status_code == 403


async def test_foreign_resources_and_experts_do_not_cross_organization(env):
    from sqlalchemy import text

    from app.modules.auth.models import WebSession
    from app.modules.experts.categories import seed_categories as seed_expert_categories
    from app.modules.skills.categories import seed_categories
    from app.modules.tenants.models import Tenant

    admin = await env.client()
    skill, blob = await skill_create(admin)
    expert = await create(admin, content=content(skills=[ref(skill)]))
    skill, target = await newer(admin, skill, blob)
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        foreign = Tenant(name="另一组织")
        db.add(foreign)
        await db.flush()
        seed_categories(db, foreign.id)
        seed_expert_categories(db, foreign.id)
        session = await db.get(WebSession, admin.session.id)
        session.tenant_id = admin.tenant.id
        await db.commit()
    other = await env.client(tenant=foreign)
    async with env.sessions() as db:
        session = await db.get(WebSession, other.session.id)
        session.tenant_id = foreign.id
        await db.commit()
    other_skill, _ = await skill_create(other, "foreign-skill")
    other_expert = await create(other, content=content(skills=[ref(other_skill)]))
    assert (
        await admin.api.get(BASE + "/skill-impact?skill_id=" + other_skill["id"])
    ).status_code == 404
    assert (await other.api.get(BASE + "/skill-impact?skill_id=" + skill["id"])).status_code == 404
    choice = selection(expert, target)
    choice["expert_id"] = other_expert["id"]
    assert (await action(admin, skill, target, [choice]))[0].status_code == 404
    assert (await admin.api.get("/api/v1/skills/" + skill["id"])).json()["revision"] == skill[
        "revision"
    ]


async def test_receipt_migration_preserves_existing_resources_and_downgrades(env):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    admin = await env.client()
    skill, _ = await skill_create(admin)
    before = (await admin.api.get("/api/v1/skills/" + skill["id"])).json()
    migration = importlib.import_module("migrations.versions.106a_dependency_commands")
    async with env.sessions() as db:
        await db.execute(text("DROP TABLE dependency_command_receipts"))
        connection = await db.connection()

        def upgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                migration.upgrade()

        await connection.run_sync(upgrade)
        await db.commit()
    assert (await admin.api.get("/api/v1/skills/" + skill["id"])).json() == before
    async with env.sessions() as db:
        connection = await db.connection()

        def downgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                migration.downgrade()

        await connection.run_sync(downgrade)
        await db.commit()
    assert (await admin.api.get("/api/v1/skills/" + skill["id"])).json() == before
