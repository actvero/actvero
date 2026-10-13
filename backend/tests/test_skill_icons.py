"""Icon parsing, authority, immutable packages and publication precedence."""
# ruff: noqa: F811

import base64
import hashlib
import importlib
from io import BytesIO

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from PIL import Image
from sqlalchemy import select, text
from test_identity_access import env  # noqa: F401
from test_skills import action, imported, package, payload

from app.modules.skills.icons import catalog, package_icon, svg_image
from app.modules.skills.models import Skill, SkillPackage, SkillVersion
from app.modules.skills.packages import inspect_package

SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<path d="M1 1L20 20" stroke="black"/></svg>'
)


def icon_package(svg=SVG):
    return package(
        {
            "test-skill/agents/openai.yaml": "interface:\n  icon_small: ./assets/icon.svg\n",
            "test-skill/assets/icon.svg": svg,
        }
    )


def test_package_icon_root_paths_and_fallback():
    parsed = inspect_package(icon_package())
    assert parsed.package_icon.startswith("data:image/svg+xml;base64,")
    assert not parsed.icon_warning
    assert parsed.sha256 == hashlib.sha256(icon_package()).hexdigest()
    result = package_icon(
        {
            "agents/openai.yaml": (
                b"interface:\n  icon_small: ./missing.png\n  icon_large: ./icon.svg"
            ),
            "icon.svg": SVG,
        },
        "",
    )
    assert result[0] and "大图标" in result[1]
    assert len(catalog()) == 560
    assert len({item["key"] for item in catalog()}) == 560


@pytest.mark.parametrize(
    "svg",
    [
        b'<svg onload="alert(1)"/>',
        b"<svg><script>alert(1)</script></svg>",
        b'<svg><image href="https://example.com/tracker"/></svg>',
        b'<svg><path fill="url(https://example.com/a)"/></svg>',
        b"<svg><foreignObject/></svg>",
        b'<!DOCTYPE svg [<!ENTITY x "xx">]><svg>&x;</svg>',
        '<!DOCTYPE svg [<!ENTITY x "xx">]><svg>&x;</svg>'.encode("utf-16"),
        b'<svg style="background:url(https://example.com)"></svg>',
        b"<svg>" + b"<path/>" * 501 + b"</svg>",
        b"<" * (256 * 1024 + 1),
    ],
)
def test_untrusted_svg_is_not_exposed_and_does_not_block_import(svg):
    parsed = inspect_package(icon_package(svg))
    assert not parsed.package_icon
    assert parsed.icon_warning


@pytest.mark.parametrize(
    "config",
    [
        b"interface:\n  icon_small: https://example.com/icon.svg",
        b"interface:\n  icon_small: ../../icon.svg",
        b"interface:\n  icon_small: /icon.svg",
        b"interface:\n  icon_small: 9",
        b"interface: &a [*a]",
        b"interface: [",
        b"a" * 16385,
    ],
)
def test_invalid_optional_yaml_does_not_block_valid_skill(config):
    parsed = inspect_package(package({"test-skill/agents/openai.yaml": config}))
    assert parsed.name == "test-skill"
    assert not parsed.package_icon and parsed.icon_warning


def test_static_svg_xml_declaration_and_namespace_are_canonicalized():
    value = svg_image(b"<?xml version='1.0' encoding='UTF-8'?>" + SVG)
    result = base64.b64decode(value.split(",", 1)[1])
    assert b"<svg xmlns=" in result or b'xmlns="http://www.w3.org/2000/svg"' in result
    assert b"<?" not in result


@pytest.mark.asyncio
async def test_skill_icon_override_auto_publication_and_authorization(env):
    admin = await env.client()
    member = await env.client(role="member")
    blob = icon_package()
    preview = await admin.api.post("/api/v1/skills/preview", content=blob)
    assert preview.json()["package_icon"]
    skill = await imported(admin, data=blob)
    assert skill["icon"]["source"] == "fallback"  # unpublished package is not active
    skill = (await action(admin, skill, "publish")).json()
    assert skill["icon"]["source"] == "package"
    path = f"/api/v1/skills/{skill['id']}"

    async def update(selection=None, omit=False, client=admin):
        body = {
            k: skill[k]
            for k in ("display_name", "description", "audience", "member_ids", "revision")
        }
        if not omit:
            body["icon_selection"] = selection
        return await client.api.put(path, json=body)

    assert (await member.api.get("/api/v1/skills/icon-catalog")).status_code == 403
    assert (
        await member.api.put(
            path,
            json={
                **{
                    k: skill[k]
                    for k in ("display_name", "description", "audience", "member_ids", "revision")
                },
                "icon_selection": {"source": "auto"},
            },
        )
    ).status_code == 403
    result = await update({"source": "library", "key": "lucide:file-text"})
    assert result.status_code == 200, result.text
    skill = result.json()
    expected_icon = skill["icon"]
    assert expected_icon["source"] == "library"
    assert (
        expected_icon["sha256"]
        == hashlib.sha256(base64.b64decode(expected_icon["image"].split(",", 1)[1])).hexdigest()
    )
    member_view = (await member.api.get(path)).json()
    assert member_view["icon"] == expected_icon
    assert member_view["icon_selection"] is None
    skill = (await update(omit=True)).json()
    assert skill["icon"] == expected_icon

    second_blob = icon_package(SVG.replace(b"black", b"red"))
    body = payload(data=second_blob, skill_id=skill["id"], revision=skill["revision"])
    body["version"] = "2.0.0"
    result = await admin.api.post("/api/v1/skills/import", json=body)
    skill = result.json()
    second = next(v for v in skill["versions"] if v["version"] == "2.0.0")
    skill = (await action(admin, skill, "publish", second["id"])).json()
    assert skill["icon"] == expected_icon
    skill = (await update({"source": "auto"})).json()
    assert skill["icon"]["source"] == "package"
    assert skill["icon"]["image"] == second["package_icon"]
    download = await admin.api.post(f"{path}/versions/{second['id']}/download")
    assert download.content == second_blob

    for choice in (
        {"source": "library", "key": "lucide:unknown"},
        {"source": "upload", "image": "https://example.com/a.png"},
        {"source": "auto", "key": "lucide:file-text"},
        {"source": "upload", "image": "data:image/png;base64,AAAA"},
    ):
        assert (await update(choice)).status_code == 422
    png = BytesIO()
    Image.new("RGB", (32, 32), "red").save(png, format="PNG")
    skill = (
        await update(
            {
                "source": "upload",
                "image": "data:image/png;base64," + base64.b64encode(png.getvalue()).decode(),
            }
        )
    ).json()
    assert skill["icon"]["source"] == "upload"
    assert skill["icon"]["image"].startswith("data:image/webp;base64,")
    assert skill["icon"]["image"] == skill["icon_selection"]["image"]
    assert (await admin.api.get(path)).json()["icon"] == skill["icon"]
    skill = (await update({"source": "auto"})).json()
    skill = (await action(admin, skill, "withdraw", second["id"])).json()
    assert skill["icon"]["source"] == "fallback"
    assert (await member.api.get(path)).status_code == 404


@pytest.mark.asyncio
async def test_icon_migration_backfills_without_changing_package_or_active_version(
    env, monkeypatch
):
    admin = await env.client()
    original = icon_package()
    skill = await imported(admin, data=original)
    skill = (await action(admin, skill, "publish")).json()
    migration = importlib.import_module("migrations.versions.79h_skills_icons")
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE skills DROP COLUMN icon_selection"))
        await db.execute(text("ALTER TABLE skill_versions DROP COLUMN package_icon"))
        await db.execute(text("ALTER TABLE skill_versions DROP COLUMN icon_warning"))

        def upgrade(connection):
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()

        await (await db.connection()).run_sync(upgrade)
        row = await db.scalar(select(Skill))
        version = await db.scalar(select(SkillVersion))
        assert row.icon_selection == {"source": "auto"}
        assert str(row.default_version_id) == skill["default_version_id"]
        assert row.revision == skill["revision"]
        assert version.package_icon == skill["icon"]["image"]
        assert version.status == "published"
        assert version.sha256 == hashlib.sha256(original).hexdigest()
        assert await db.scalar(select(SkillPackage.data)) == original
