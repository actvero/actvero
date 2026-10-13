"""Real DB lifecycle, authorization and immutable package coverage."""
# ruff: noqa: F811

import asyncio
import base64
import hashlib
import importlib
import stat
from datetime import timedelta
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from test_identity_access import env  # noqa: F401

from app.modules.audit.models import AuditEvent
from app.modules.auth.service import now
from app.modules.members.models import Membership
from app.modules.skills.models import Skill, SkillDistribution, SkillPackage, SkillVersion
from app.modules.skills.packages import MAX_FILE, inspect_package


def package(extra=None, markdown=None):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "test-skill/SKILL.md",
            markdown
            or (
                "---\nname: test-skill\ndescription: Skill for acceptance tests\n"
                "---\n# Instructions\nRead the input.\n"
            ),
        )
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    return output.getvalue()


def payload(data=None, **kwargs):
    return dict(
        display_name="测试技能",
        description="测试上传及授权",
        audience="organization",
        member_ids=[],
        version="1.0.0",
        package_base64=base64.b64encode(data or package()).decode(),
        **kwargs,
    )


async def imported(client, **kwargs):
    response = await client.api.post("/api/v1/skills/import", json=payload(**kwargs))
    assert response.status_code == 200, response.text
    return response.json()


async def action(client, skill, name, version=None):
    return await client.api.post(
        f"/api/v1/skills/{skill['id']}/versions/{version or skill['versions'][0]['id']}/actions",
        json={"revision": skill["revision"], "action": name},
    )


@pytest.mark.asyncio
async def test_upload_publish_single_active_withdraw_and_exact_download(env):
    admin = await env.client()
    member = await env.client(role="member")
    blob = package()
    preview = await admin.api.post("/api/v1/skills/preview", content=blob)
    assert preview.status_code == 200
    assert preview.json()["sha256"] == hashlib.sha256(blob).hexdigest()
    skill = await imported(admin, data=blob)
    version = skill["versions"][0]["id"]
    path = f"/api/v1/skills/{skill['id']}/versions/{version}"
    assert (await member.api.get("/api/v1/skills")).json()["items"] == []
    assert (await member.api.get(path + "/overview")).status_code == 404
    assert (await member.api.post(path + "/download")).status_code == 404
    skill = (await action(admin, skill, "publish")).json()
    assert skill["default_version_id"] == version
    assert len((await member.api.get("/api/v1/skills")).json()["items"]) == 1
    assert (await action(admin, skill, "default")).status_code == 422
    response = await member.api.post(path + "/download")
    assert response.content == blob
    assert response.headers["x-content-sha256"] == hashlib.sha256(blob).hexdigest()
    assert (
        await member.api.get(path + "/file", params={"path": "test-skill/SKILL.md"})
    ).status_code == 200
    assert (await member.api.get(path + "/file", params={"path": "../../.env"})).status_code == 404
    withdrawn = (await action(admin, skill, "withdraw")).json()
    assert withdrawn["default_version_id"] is None
    assert (await member.api.post(path + "/download")).status_code == 404
    assert (await admin.api.get("/api/v1/skills/distributions")).json()["total"] == 1
    assert (await member.api.get("/api/v1/skills/distributions")).status_code == 403


@pytest.mark.asyncio
async def test_publication_replaces_previous_version_and_rollback_preserves_packages(env):
    admin = await env.client()
    member = await env.client(role="member")
    original = package()
    skill = await imported(admin, data=original)
    skill = (await action(admin, skill, "publish")).json()
    first = skill["versions"][0]["id"]
    body = payload(
        data=package({"test-skill/new.txt": "new content"}),
        skill_id=skill["id"],
        revision=skill["revision"],
    )
    body["version"] = "2.0.0"
    skill = (await admin.api.post("/api/v1/skills/import", json=body)).json()
    second = skill["versions"][0]["id"]
    assert skill["default_version_id"] == first
    visible = (await member.api.get("/api/v1/skills/" + skill["id"])).json()
    assert [v["id"] for v in visible["versions"]] == [first]
    skill = (await action(admin, skill, "publish", second)).json()
    assert skill["default_version_id"] == second
    assert {v["id"]: v["status"] for v in skill["versions"]} == {
        first: "superseded",
        second: "published",
    }
    visible = (await member.api.get("/api/v1/skills")).json()["items"][0]
    assert [v["id"] for v in visible["versions"]] == [second]
    old_path = f"/api/v1/skills/{skill['id']}/versions/{first}"
    assert (await member.api.get(old_path + "/overview")).status_code == 404
    assert (
        await member.api.get(old_path + "/file", params={"path": "test-skill/SKILL.md"})
    ).status_code == 404
    assert (await member.api.post(old_path + "/download")).status_code == 404
    assert (await admin.api.get(old_path + "/overview")).status_code == 200
    for version in [first, second]:
        assert (
            await admin.api.delete(
                f"/api/v1/skills/{skill['id']}/versions/{version}",
                params={"revision": skill["revision"]},
            )
        ).status_code == 409
    # The database also rejects two active versions if application locking is bypassed.
    async with env.sessions() as db:
        row = await db.get(SkillVersion, UUID(first))
        row.status = "published"
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
    skill = (await action(admin, skill, "publish", first)).json()
    assert skill["default_version_id"] == first
    assert [v["id"] for v in skill["versions"] if v["status"] == "published"] == [first]
    assert (await member.api.post(old_path + "/download")).content == original
    skill = (await action(admin, skill, "withdraw", first)).json()
    assert skill["default_version_id"] is None
    assert (await member.api.get("/api/v1/skills")).json()["items"] == []
    async with env.sessions() as db:
        logs = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "skills.withdraw"))
        )
        assert len(logs) == 3


@pytest.mark.asyncio
async def test_concurrent_publications_of_distinct_versions_have_one_winner(env):
    admin = await env.client()
    another = await env.client()
    skill = await imported(admin)
    first = skill["versions"][0]["id"]
    body = payload(skill_id=skill["id"], revision=skill["revision"])
    body["version"] = "2.0.0"
    skill = (await admin.api.post("/api/v1/skills/import", json=body)).json()
    second = skill["versions"][0]["id"]
    results = await asyncio.gather(
        action(admin, skill, "publish", first), action(another, skill, "publish", second)
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    current = (await admin.api.get("/api/v1/skills/" + skill["id"])).json()
    active = [v["id"] for v in current["versions"] if v["status"] == "published"]
    assert active == [current["default_version_id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("previous_default", ["older", "none", "draft"])
async def test_single_active_migration_preserves_choice_and_all_packages(
    env, monkeypatch, previous_default
):
    admin = await env.client()
    migration = importlib.import_module("migrations.versions.79g_skills_single_active_version")
    async with env.sessions() as db:
        await db.execute(text("DROP INDEX uq_skill_versions_one_published"))
        skill = Skill(
            tenant_id=admin.member.tenant_id,
            name="legacy",
            display_name="历史技能",
            description="迁移验证",
            audience="organization",
            member_ids=[],
        )
        db.add(skill)
        await db.flush()
        versions = [
            SkillVersion(
                skill_id=skill.id,
                version=f"{n}.0.0",
                uploader_name="测试",
                status="published" if n < 3 else "draft",
                published_at=now() + timedelta(seconds=n) if n < 3 else None,
                sha256="test",
                size=3,
                files=[],
                skill_md="original",
            )
            for n in (1, 2, 3)
        ]
        db.add_all(versions)
        await db.flush()
        skill.default_version_id = (
            versions[0].id
            if previous_default == "older"
            else versions[2].id
            if previous_default == "draft"
            else None
        )
        for v in versions:
            db.add(SkillPackage(version_id=v.id, data=b"zip"))
        await db.flush()
        expected = versions[0].id if previous_default == "older" else versions[1].id

        def upgrade(connection):
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()

        await (await db.connection()).run_sync(upgrade)
        await db.refresh(skill)
        for v in versions:
            await db.refresh(v)
        assert skill.default_version_id == expected
        assert skill.revision == 2
        assert [v.id for v in versions if v.status == "published"] == [expected]
        assert versions[2].status == "draft"
        assert list(await db.scalars(select(SkillPackage.data))) == [b"zip"] * 3
        versions[2].status = "published"
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()


@pytest.mark.asyncio
async def test_shared_scope_revocation_and_removed_members_close_every_version(env):
    admin = await env.client()
    member = await env.client(role="member")
    other = await env.client(role="member")
    skill = await imported(admin)
    skill = (await action(admin, skill, "publish")).json()
    first = skill["versions"][0]["id"]
    body = payload(skill_id=skill["id"], revision=skill["revision"])
    body["version"] = "2.0.0"
    skill = (await admin.api.post("/api/v1/skills/import", json=body)).json()
    assert skill["versions"][0]["status"] == "draft"
    skill = (await action(admin, skill, "publish")).json()
    second = skill["versions"][0]["id"]
    update = {k: skill[k] for k in ["display_name", "description", "revision"]}
    update.update(audience="selected", member_ids=[str(member.member.id)])
    skill = (await admin.api.put("/api/v1/skills/" + skill["id"], json=update)).json()
    assert (await member.api.get("/api/v1/skills/" + skill["id"])).status_code == 200
    assert (await other.api.get("/api/v1/skills/" + skill["id"])).status_code == 404
    for version in [first, second]:
        assert (
            await other.api.post(f"/api/v1/skills/{skill['id']}/versions/{version}/download")
        ).status_code == 404
    update.update(revision=skill["revision"], audience="administrators", member_ids=[])
    skill = (await admin.api.put("/api/v1/skills/" + skill["id"], json=update)).json()
    assert (await member.api.get("/api/v1/skills/" + skill["id"])).status_code == 404
    async with env.sessions() as db:
        row = await db.get(Membership, admin.member.id)
        row.status = "paused"
        await db.commit()
    assert (await admin.api.get("/api/v1/skills")).status_code == 403


@pytest.mark.asyncio
async def test_new_version_preserves_shared_scope_even_after_member_paused(env):
    admin = await env.client()
    member = await env.client(role="member")
    body = payload()
    body.update(audience="selected", member_ids=[str(member.member.id)])
    skill = (await admin.api.post("/api/v1/skills/import", json=body)).json()
    async with env.sessions() as db:
        row = await db.get(Membership, member.member.id)
        row.status = "paused"
        await db.commit()
    body.update(skill_id=skill["id"], revision=skill["revision"], version="2.0.0")
    response = await admin.api.post("/api/v1/skills/import", json=body)
    assert response.status_code == 200, response.text
    skill = response.json()
    assert skill["audience"] == "selected"
    assert skill["member_ids"] == [str(member.member.id)]
    body.update(revision=skill["revision"], version="3.0.0", audience="organization", member_ids=[])
    response = await admin.api.post("/api/v1/skills/import", json=body)
    assert response.status_code == 200, response.text
    skill = response.json()
    assert skill["audience"] == "selected"
    assert skill["member_ids"] == [str(member.member.id)]
    assert len(skill["versions"]) == 3
    assert (await member.api.get("/api/v1/skills/" + skill["id"])).status_code == 403


@pytest.mark.asyncio
async def test_roles_csrf_duplicate_concurrency_and_foreign_ids(env):
    admin = await env.client()
    member = await env.client(role="member")
    assert (await member.api.post("/api/v1/skills/import", json=payload())).status_code == 403
    assert (
        await admin.api.post(
            "/api/v1/skills/import", json=payload(), headers={"x-csrf-token": "invalid"}
        )
    ).status_code == 403
    skill = await imported(admin)
    assert (await admin.api.post("/api/v1/skills/import", json=payload())).status_code == 409
    body = payload(skill_id=skill["id"], revision=skill["revision"])
    assert (await admin.api.post("/api/v1/skills/import", json=body)).status_code == 409
    responses = await asyncio.gather(
        action(admin, skill, "publish"), action(admin, skill, "publish")
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert (await admin.api.get("/api/v1/skills/" + str(uuid4()))).status_code == 404
    assert (
        await admin.api.post(f"/api/v1/skills/{skill['id']}/versions/{uuid4()}/download")
    ).status_code == 404
    async with env.sessions() as db:
        assert not (await db.scalars(select(SkillDistribution))).all()


@pytest.mark.parametrize(
    "path",
    [
        "../evil",
        "/absolute",
        "a\\b",
        "test-skill/.env",
        "test-skill/.git/config",
        "test-skill/a/../../b",
        "test-skill/a:stream",
    ],
)
def test_unsafe_paths_rejected(path):
    with pytest.raises(HTTPException):
        inspect_package(package({path: "bad"}))


def test_special_files_multiple_skills_and_bombs_rejected():
    link = ZipInfo("test-skill/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    for data in [
        package({link: "/etc/passwd"}),
        package({"other/SKILL.md": "bad"}),
        package({"test-skill/huge": "a" * (MAX_FILE + 1)}),
        package({"test-skill/skill.md": "case collision"}),
    ]:
        with pytest.raises(HTTPException):
            inspect_package(data)


@pytest.mark.parametrize(
    "markdown",
    [
        "no frontmatter",
        "---\nname: test-skill\ndescription: &x [*x]\n---\n",
        "---\nname: ../evil\ndescription: bad\n---\n",
    ],
)
def test_invalid_metadata_rejected(markdown):
    with pytest.raises(HTTPException):
        inspect_package(package(markdown=markdown))
