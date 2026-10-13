"""Actual PostgreSQL isolation, immutable downloads and native token boundaries."""

import asyncio
import importlib
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from test_desktop import bearer, login, native_client
from test_desktop_mcp import token
from test_identity_access import env as identity_env
from test_skills import action, package, payload

from app.modules.auth.service import digest, now
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop_mcp.models import ResourceToken
from app.modules.members.models import Membership
from app.modules.skills.models import SkillDistribution, SkillPackage

BASE = "/api/v1/desktop/skills"
env = identity_env
pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


async def create(web, name="test-skill", publish=True, **changes):
    blob = package(markdown=f"---\nname: {name}\ndescription: Example\n---\n# Usage\nRead input.")
    # package helper uses a wrapping directory; rename it with the stable name.
    if name != "test-skill":
        from io import BytesIO
        from zipfile import ZipFile

        out = BytesIO()
        with ZipFile(BytesIO(blob)) as src, ZipFile(out, "w") as dest:
            for path in src.namelist():
                dest.writestr(path.replace("test-skill/", name + "/"), src.read(path))
        blob = out.getvalue()
    response = await web.api.post("/api/v1/skills/import", json={**payload(data=blob), **changes})
    assert response.status_code == 200, response.text
    skill = response.json()
    if publish:
        response = await action(web, skill, "publish")
        assert response.status_code == 200, response.text
        skill = response.json()
    return skill, blob


async def native(env, monkeypatch, api, web):
    root, _ = await login(env, monkeypatch, api, web)
    return root, bearer(await token(api, root, "skills:catalog"))


def download_input(detail):
    version = detail["current_version"]
    return {"version_id": version["id"], "sha256": version["sha256"]}


async def test_category_metadata_preservation_validation_and_filter(env):
    admin, member = await env.client(), await env.client(role="member")
    skill, _ = await create(admin, category="design")
    assert skill["category"] == "design"
    choices = (await admin.api.get("/api/v1/skills/categories")).json()
    assert {c["id"]: c["name"] for c in choices}["design"] == "设计创意"
    assert len(choices) == 9
    assert (await admin.api.get("/api/v1/skills?category=design")).json()["total"] == 1
    assert (await admin.api.get("/api/v1/skills?category=office")).json()["total"] == 0
    metadata = {
        k: skill[k] for k in ("display_name", "description", "audience", "member_ids", "revision")
    }
    path = "/api/v1/skills/" + skill["id"]
    assert (await member.api.put(path, json={**metadata, "category": "office"})).status_code == 403
    assert (await admin.api.put(path, json={**metadata, "category": "invented"})).status_code == 422
    unchanged = (await admin.api.put(path, json=metadata)).json()
    assert unchanged["category"] == "design"
    changed = await admin.api.put(
        path, json={**metadata, "revision": unchanged["revision"], "category": "office"}
    )
    assert changed.status_code == 200
    skill = changed.json()
    assert skill["category"] == "office"
    response = await admin.api.post(
        "/api/v1/skills/import",
        json={
            **payload(),
            "skill_id": skill["id"],
            "revision": skill["revision"],
            "version": "2.0.0",
            "category": "data",
        },
    )
    assert response.status_code == 200
    assert response.json()["category"] == "office"  # new package must not overwrite shared metadata
    assert (await admin.api.get("/api/v1/skills?category=invalid")).status_code == 422


async def test_catalog_categories_scope_and_no_desktop_admin_inspection_bypass(env, monkeypatch):
    admin, alice, bob = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    common, _ = await create(admin, category="office")
    private, _ = await create(
        admin,
        "private-skill",
        audience="selected",
        member_ids=[str(alice.member.id)],
        category="data",
    )
    managers, _ = await create(admin, "admin-skill", audience="administrators", category="design")
    await create(admin, "draft-skill", publish=False, category="content")
    gone, _ = await create(admin, "gone-skill", category="office")
    await action(admin, gone, "withdraw")
    async with native_client(env) as api:
        for web, expected in (
            (admin, [common, managers]),
            (alice, [common, private]),
            (bob, [common]),
        ):
            _, headers = await native(env, monkeypatch, api, web)
            response = await api.get(BASE, headers=headers)
            assert response.status_code == 200, response.text
            body = response.json()
            assert {s["id"] for s in body["items"]} == {s["id"] for s in expected}
            assert body["total"] == len(expected) and body["page_size"] == 20
            counts = (await api.get(BASE + "/categories", headers=headers)).json()
            assert sum(c["count"] for c in counts) == len(expected)
            assert next(c["count"] for c in counts if c["id"] == "data") == (
                1 if web == alice else 0
            )
            assert (await api.get(BASE, params={"category": "office"}, headers=headers)).json()[
                "total"
            ] == 1
            assert (await api.get(BASE, params={"q": "private-skill"}, headers=headers)).json()[
                "total"
            ] == (1 if web == alice else 0)
            filtered = (await api.get(BASE + "/categories?q=private-skill", headers=headers)).json()
            assert sum(c["count"] for c in filtered) == (1 if web == alice else 0)
            assert (await api.get(BASE + "?page=2", headers=headers)).json()["items"] == []
            if web != alice:
                assert (
                    await api.get(BASE + "/" + private["id"], headers=headers)
                ).status_code == 404
            assert (await api.get(BASE + "/" + gone["id"], headers=headers)).status_code == 404
            assert all(
                key not in body["items"][0]
                for key in ("versions", "member_ids", "audience", "icon_selection")
            )


async def test_detail_preview_download_exact_bytes_and_audit(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    skill, blob = await create(
        admin, category="office", icon_selection={"source": "library", "key": "lucide:book-open"}
    )
    async with native_client(env) as api:
        root, headers = await native(env, monkeypatch, api, member)
        path = BASE + "/" + skill["id"]
        response = await api.get(path, headers=headers)
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail["category"] == {"id": "office", "name": "办公协同"}
        assert detail["entrypoint"] == "test-skill/SKILL.md"
        assert detail["icon"]["image"].startswith("data:image/")
        assert "# Usage" in detail["skill_md"]
        proof = download_input(detail)
        preview = await api.get(
            path + "/file",
            headers=headers,
            params={"version_id": proof["version_id"], "path": detail["entrypoint"]},
        )
        assert preview.json()["content"].startswith("---\nname:")
        assert preview.json()["content"].endswith(detail["skill_md"])
        invalid = await api.get(
            path + "/file",
            headers=headers,
            params={"version_id": proof["version_id"], "path": "../../.env"},
        )
        assert invalid.status_code == 404 and invalid.json()["error"]["code"] == "file_unavailable"
        downloaded = await api.post(path + "/download", headers=headers, json=proof)
        assert downloaded.status_code == 200 and downloaded.content == blob
        assert downloaded.headers["x-content-sha256"] == proof["sha256"]
        assert downloaded.headers["x-skill-version-id"] == proof["version_id"]
        assert downloaded.headers["cache-control"] == "no-store"
        assert downloaded.headers["content-type"] == "application/zip"
        assert (
            await api.post(path + "/download", headers=headers, json={**proof, "sha256": "0" * 64})
        ).status_code == 409
        async with env.sessions() as db:
            audit = (await db.scalars(select(SkillDistribution))).one()
            assert (
                audit.source == "desktop"
                and str(audit.device_session_id) == root["device_session_id"]
            )
            assert audit.actor_id == member.user.id and audit.client_version == "0.1.0"
            stored = await db.get(SkillPackage, UUID(proof["version_id"]))
            assert stored.data == blob


async def test_update_publish_race_rollback_and_withdraw(env, monkeypatch):
    admin = await env.client()
    skill, _ = await create(admin)
    async with native_client(env) as api:
        _, headers = await native(env, monkeypatch, api, admin)
        path = BASE + "/" + skill["id"]
        original = (await api.get(path, headers=headers)).json()
        proof = download_input(original)
        installed = {"items": [{"skill_id": skill["id"], **proof}]}

        async def check():
            return (
                await api.post(BASE + "/check-updates", headers=headers, json=installed)
            ).json()["items"][0]

        assert (await check())["status"] == "current"
        new = await admin.api.post(
            "/api/v1/skills/import",
            json={
                **payload(),
                "skill_id": skill["id"],
                "revision": skill["revision"],
                "version": "2.0.0",
            },
        )
        skill = new.json()
        second = next(v["id"] for v in skill["versions"] if v["version"] == "2.0.0")
        assert (await check())["status"] == "current"  # draft never affects consumers
        skill = (await action(admin, skill, "publish", second)).json()
        assert (await check())["status"] == "update_available"
        denied = await api.post(path + "/download", headers=headers, json=proof)
        assert (
            denied.status_code == 409 and denied.json()["error"]["code"] == "skill_version_changed"
        )
        assert (
            await api.get(
                path + "/file",
                headers=headers,
                params={"version_id": proof["version_id"], "path": original["entrypoint"]},
            )
        ).status_code == 409
        current = (await api.get(path, headers=headers)).json()
        installed["items"][0].update(download_input(current))
        skill = (await action(admin, skill, "publish", proof["version_id"])).json()
        assert (await check())["status"] == "update_available"  # rollback is also an update
        await action(admin, skill, "withdraw", proof["version_id"])
        unavailable = await check()
        assert unavailable == {"skill_id": skill["id"], "status": "unavailable", "skill": None}
        assert (await api.post(path + "/download", headers=headers, json=proof)).status_code == 404
        unknown = await api.post(
            BASE + "/check-updates",
            headers=headers,
            json={"items": [{"skill_id": str(uuid4()), **proof}]},
        )
        assert unknown.json()["items"][0]["skill"] is None
        for items in ([], installed["items"] * 2, installed["items"] * 101):
            assert (
                await api.post(BASE + "/check-updates", headers=headers, json={"items": items})
            ).status_code == 422


async def test_token_boundaries_expiry_devices_and_live_member_revocation(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    skill, _ = await create(admin)
    async with native_client(env) as api:
        root, headers = await native(env, monkeypatch, api, member)
        other, other_headers = await native(env, monkeypatch, api, member)
        mcp = bearer(await token(api, root))
        for bad in (bearer(root), {}):
            assert (await api.get(BASE, headers=bad)).status_code == 401
        assert (await api.get(BASE, headers=mcp)).status_code == 403
        assert (await api.get("/api/v1/desktop/mcp/connectors", headers=headers)).status_code == 403
        assert (await api.get("/api/v1/skills", headers=headers)).status_code == 401
        assert (await api.get("/api/v1/desktop/me", headers=headers)).status_code == 401
        assert (await admin.api.get(BASE, headers=headers)).status_code == 401
        assert (
            await api.get(BASE, headers={**headers, "Origin": "http://test"})
        ).status_code == 401
        async with env.sessions() as db:
            row = await db.get(
                ResourceToken, digest(headers["Authorization"].removeprefix("Bearer "))
            )
            row.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await api.get(BASE, headers=headers)).json()["error"][
            "code"
        ] == "resource_token_expired"
        headers = bearer(await token(api, root, "skills:catalog"))
        await api.post("/api/v1/desktop/logout", json={"refresh_token": root["refresh_token"]})
        assert (await api.get(BASE, headers=headers)).json()["error"]["code"] == "device_revoked"
        assert (await api.get(BASE, headers=other_headers)).status_code == 200
        async with env.sessions() as db:
            row = await db.get(Membership, member.member.id)
            row.status = "paused"
            await db.commit()
        assert (await api.get(BASE, headers=other_headers)).json()["error"][
            "code"
        ] == "member_suspended"
        assert (
            await api.post(
                "/api/v1/desktop/resource-tokens",
                headers=bearer(other),
                json={"resource": "skills:catalog"},
            )
        ).status_code == 403


async def test_download_and_scope_change_are_serialized(env, monkeypatch):
    from app.modules.desktop_skills import service

    admin, member = await env.client(), await env.client(role="member")
    skill, _ = await create(admin)
    async with native_client(env) as api:
        _, headers = await native(env, monkeypatch, api, member)
        path = BASE + "/" + skill["id"]
        detail = (await api.get(path, headers=headers)).json()
        reached, release = asyncio.Event(), asyncio.Event()
        original = service.current

        async def waiting(*args, **kwargs):
            reached.set()
            await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(service, "current", waiting)
        downloading = asyncio.create_task(
            api.post(path + "/download", headers=headers, json=download_input(detail))
        )
        await asyncio.wait_for(reached.wait(), 5)
        metadata = {k: skill[k] for k in ("display_name", "description", "revision")}
        withdrawing = asyncio.create_task(
            admin.api.put(
                "/api/v1/skills/" + skill["id"],
                json={**metadata, "audience": "administrators", "member_ids": []},
            )
        )
        try:
            await asyncio.sleep(0.1)
            assert not withdrawing.done()
        finally:
            release.set()
        assert (await downloading).status_code == 200
        assert (await withdrawing).status_code == 200
        assert (
            await api.post(path + "/download", headers=headers, json=download_input(detail))
        ).status_code == 404


async def test_category_migration_preserves_published_packages(env):
    admin = await env.client()
    skill, blob = await create(admin)
    migration = importlib.import_module("migrations.versions.79i_skills_desktop")
    editable = importlib.import_module("migrations.versions.79j_skill_categories")
    async with env.sessions() as db:
        conn = await db.connection()

        def cycle(sync):
            with Operations.context(MigrationContext.configure(sync)):
                editable.downgrade()
                migration.downgrade()
                migration.upgrade()
                editable.upgrade()

        await conn.run_sync(cycle)
        row = (
            await db.execute(
                text("SELECT category, default_version_id, revision FROM skills WHERE id=:id"),
                {"id": UUID(skill["id"])},
            )
        ).one()
        assert row.category == "uncategorized"
        assert str(row.default_version_id) == skill["default_version_id"]
        assert row.revision == skill["revision"]
        assert (await db.get(SkillPackage, UUID(skill["default_version_id"]))).data == blob
