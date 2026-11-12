"""Verify package validation and the organization release lifecycle."""

import hashlib
import json
import tarfile
from base64 import b64encode
from io import BytesIO
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from PIL import Image
from test_desktop import bearer, login, native_client
from test_desktop_mcp import token
from test_identity_access import env  # noqa: F401

from app.modules.desktop.oidc import NativeIdentity
from app.modules.workbenches.models import WorkbenchPackage
from app.modules.workbenches.packages import inspect

BASE = "/api/v1/workbenches"
BINARY = {"content-type": "application/octet-stream"}


def package(version="1.0.0", extra=None, fields=None, icon=None, icon_path="./assets/icon.png"):
    manifest = {
        "name": "@test/workbench",
        "version": version,
        "description": "用于组织试用",
        "engines": {"dsh": "0.2.1-rc.3"},
        "exports": {".": "./lib/index.js", "./client": "./lib/client.js"},
        "dsh": {
            "actveroWorkbench": 1,
            **({"actveroWorkbenchConfig": fields} if fields is not None else {}),
            **({"actveroWorkbenchIcon": icon_path} if icon is not None else {}),
            "bundle": {"patch": "./cordis.patch.yml"},
            "client": {"platform": "web", "inject": ["@actvero/dsh-capability-ui"]},
        },
    }
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        entries = {
            "package/package.json": json.dumps(manifest).encode(),
            "package/locale/en.json": json.dumps({"meta": {"title": "测试工作台"}}).encode(),
            "package/lib/index.js": b"export {}",
            "package/lib/client.js": b"export {}",
            "package/cordis.patch.yml": b"[]",
        }
        if icon is not None:
            entries["package/assets/icon.png"] = icon
        for name, data in entries.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(data)
            archive.addfile(entry, BytesIO(data))
        if extra:
            archive.addfile(extra)
    return output.getvalue()


def png_icon():
    output = BytesIO()
    Image.new("RGB", (2, 2), "blue").save(output, format="PNG")
    return output.getvalue()


def test_inspects_real_manifest_and_rejects_non_file_entries():
    data = package("1.2.3-rc.4")
    info = inspect(data)
    assert info.display_name == "测试工作台"
    assert info.version == "1.2.3-rc.4"
    assert info.sha256 == hashlib.sha256(data).hexdigest()
    linked = tarfile.TarInfo("package/lib/linked.js")
    linked.type = tarfile.SYMTYPE
    linked.linkname = "index.js"
    with pytest.raises(ValueError, match="只允许普通文件"):
        inspect(package(extra=linked))
    with pytest.raises(ValueError, match="文件路径无效"):
        inspect(package(extra=tarfile.TarInfo("package/../file")))
    field = {"key": "SERVICE_URL", "label": "服务地址", "kind": "url"}
    with pytest.raises(ValueError, match="重复的运行配置 Key"):
        inspect(package(fields=[field, field]))
    assert info.icon_data_url is None


def test_reads_a_declared_avatar_and_rejects_invalid_files():
    image = png_icon()
    assert inspect(package(icon=image)).icon_data_url == (
        "data:image/png;base64," + b64encode(image).decode("ascii")
    )
    with pytest.raises(ValueError, match="格式与扩展名不符"):
        inspect(package(icon=b"<svg/>"))
    with pytest.raises(ValueError, match="包内不超过 64 KiB"):
        inspect(package(icon=image, icon_path="./assets/missing.png"))
    with pytest.raises(ValueError, match="须指向"):
        inspect(package(icon=image, icon_path="./assets/../icon.png"))


@pytest.mark.asyncio
async def test_release_scope_revisions_and_immutable_bytes(env):  # noqa: F811
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    image = png_icon()
    icon = "data:image/png;base64," + b64encode(image).decode("ascii")
    data = package(icon=image)
    assert (await member.api.get(BASE)).status_code == 403
    assert (await member.api.post(BASE, content=data, headers=BINARY)).status_code == 403
    assert (await admin.api.post(BASE, content=b"invalid", headers=BINARY)).status_code == 422
    result = await admin.api.post(BASE, content=data, headers=BINARY)
    assert result.status_code == 201, result.text
    item = result.json()
    first = item["versions"][0]["id"]
    root = f"{BASE}/{item['id']}"
    assert item["status"] == "draft"
    assert item["audience"] == "administrators"
    assert item["icon_data_url"] == icon
    assert (await admin.api.get(BASE)).json()["items"][0]["icon_data_url"] == icon
    invalid = await admin.api.put(
        f"{root}/scope",
        json={
            "revision": item["revision"],
            "audience": "selected",
            "member_ids": [str(uuid4())],
        },
    )
    assert invalid.status_code == 422
    result = await admin.api.put(
        f"{root}/scope",
        json={
            "revision": item["revision"],
            "audience": "selected",
            "member_ids": [str(member.member.id)],
        },
    )
    assert result.status_code == 200, result.text
    scoped = result.json()
    assert scoped["member_ids"] == [str(member.member.id)]
    path = f"{root}/versions/{first}"
    assert (
        await admin.api.post(path + "/publish", json={"revision": item["revision"]})
    ).status_code == 409
    result = await admin.api.post(
        path + "/publish", json={"revision": scoped["revision"], "release_notes": "首发"}
    )
    assert result.status_code == 200, result.text
    item = result.json()
    assert item["current_version"] == "1.0.0"
    assert (
        await admin.api.post(
            f"{root}/versions",
            params={"revision": item["revision"]},
            content=package("0.9.0"),
            headers=BINARY,
        )
    ).status_code == 409
    result = await admin.api.post(
        f"{root}/versions",
        params={"revision": item["revision"]},
        content=package("1.1.0"),
        headers=BINARY,
    )
    assert result.status_code == 201, result.text
    item = result.json()
    second = item["versions"][0]["id"]
    assert item["icon_data_url"] == icon
    assert (await admin.api.get(BASE)).json()["items"][0]["icon_data_url"] == icon
    result = await admin.api.post(
        f"{root}/versions/{second}/publish", json={"revision": item["revision"]}
    )
    assert result.status_code == 200, result.text
    item = result.json()
    assert item["icon_data_url"] is None
    assert (await admin.api.get(BASE)).json()["items"][0]["icon_data_url"] is None
    assert {v["version"]: v["status"] for v in item["versions"]} == {
        "1.0.0": "superseded",
        "1.1.0": "published",
    }
    result = await admin.api.post(
        f"{root}/versions/{second}/withdraw", json={"revision": item["revision"]}
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "withdrawn"
    assert result.json()["current_version"] is None
    found = await admin.api.get(BASE, params={"status": "withdrawn", "q": "测试"})
    assert found.status_code == 200, found.text
    assert [entry["id"] for entry in found.json()["items"]] == [item["id"]]
    async with env.sessions() as db:
        original = await db.get(WorkbenchPackage, UUID(first))
        assert original.data == data


@pytest.mark.asyncio
async def test_runtime_config_follows_org_scope_and_running_version(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    url = {"key": "SERVICE_URL", "label": "服务地址", "kind": "url", "required": True}
    image = png_icon()
    first_bytes = package(fields=[url], icon=image)
    draft = await admin.api.post(BASE, content=first_bytes, headers=BINARY)
    assert draft.status_code == 201, draft.text
    item = draft.json()
    root = f"{BASE}/{item['id']}"
    first = item["versions"][0]["id"]

    async def save(version_id, values):
        return await admin.api.put(
            f"{root}/runtime-config",
            json={"revision": item["revision"], "version_id": version_id, "values": values},
        )

    async def publish(version_id):
        return await admin.api.post(
            f"{root}/versions/{version_id}/publish", json={"revision": item["revision"]}
        )

    blocked = await publish(first)
    assert blocked.status_code == 409
    assert "服务地址" in blocked.text
    assert (await save(first, {"UNKNOWN": "bad"})).status_code == 422
    assert (await save(first, {"SERVICE_URL": "ftp://example.test"})).status_code == 422
    response = await save(first, {"SERVICE_URL": "https://first.example.test"})
    assert response.status_code == 200, response.text
    item = response.json()
    response = await publish(first)
    assert response.status_code == 200, response.text
    item = response.json()
    async with native_client(env) as desktop:
        account, _ = await login(env, monkeypatch, desktop, member)
        headers = bearer(await token(desktop, account, "workbenches:config"))

        native = "/api/v1/desktop/workbenches"
        pin = {
            "workbench_id": item["id"],
            "version_id": first,
            "sha256": hashlib.sha256(first_bytes).hexdigest(),
        }

        async def list_releases():
            response = await desktop.get(native, headers=headers)
            assert response.status_code == 200, response.text
            return response.json()["items"]

        async def check(release):
            response = await desktop.post(f"{native}/check-updates", json=release, headers=headers)
            assert response.status_code == 200, response.text
            return response.json()

        async def download(release):
            return await desktop.post(f"{native}/download", json=release, headers=headers)

        assert await list_releases() == []
        assert await check(pin) == {"status": "unavailable", "adopted_usable": False}
        assert (await download(pin)).status_code == 404

        async def runtime(version):
            return await desktop.post(
                "/api/v1/desktop/workbenches/config",
                json={"package_name": "@test/workbench", "version": version},
                headers=headers,
            )

        assert (await runtime("1.0.0")).status_code == 404
        scope = await admin.api.put(
            f"{root}/scope",
            json={
                "revision": item["revision"],
                "audience": "selected",
                "member_ids": [str(member.member.id)],
            },
        )
        assert scope.status_code == 200, scope.text
        item = scope.json()
        assert (await runtime("1.0.0")).json()["values"] == {
            "SERVICE_URL": "https://first.example.test"
        }
        catalog = await list_releases()
        assert len(catalog) == 1 and catalog[0]["version_id"] == first
        assert catalog[0]["size"] == len(first_bytes)
        assert catalog[0]["icon_data_url"] == (
            "data:image/png;base64," + b64encode(image).decode("ascii")
        )
        assert await check(pin) == {"status": "current", "adopted_usable": True}
        received = await download(pin)
        assert received.status_code == 200
        assert received.headers["cache-control"] == "no-store"
        assert received.content == first_bytes
        wrong_pin = {**pin, "sha256": "0" * 64}
        assert (await check(wrong_pin))["adopted_usable"] is False
        assert (await download(wrong_pin)).status_code == 409

        new_field = {"key": "REGION", "label": "默认区域", "default": "华东"}
        new = await admin.api.post(
            f"{root}/versions",
            params={"revision": item["revision"]},
            content=package("2.0.0", fields=[url, new_field]),
            headers=BINARY,
        )
        assert new.status_code == 201, new.text
        item = new.json()
        second = item["versions"][0]["id"]
        assert (await runtime("2.0.0")).status_code == 404
        assert (await list_releases())[0]["version_id"] == first
        response = await publish(second)
        assert response.status_code == 200, response.text
        item = response.json()
        assert (await list_releases())[0]["version_id"] == second
        assert await check(pin) == {"status": "update_available", "adopted_usable": True}
        assert (await download(pin)).status_code == 409
        response = await save(second, {"SERVICE_URL": "https://second.example.test"})
        assert response.status_code == 200, response.text
        item = response.json()
        assert (await runtime("1.0.0")).json()["values"] == {
            "SERVICE_URL": "https://second.example.test"
        }
        assert (await runtime("2.0.0")).json()["values"] == {
            "SERVICE_URL": "https://second.example.test",
            "REGION": "华东",
        }
        response = await admin.api.post(
            f"{root}/versions/{second}/withdraw", json={"revision": item["revision"]}
        )
        assert response.status_code == 200
        assert (await runtime("1.0.0")).status_code == 404
        assert (await runtime("2.0.0")).status_code == 404
        assert await list_releases() == []
        assert await check(pin) == {"status": "unavailable", "adopted_usable": False}
        assert (await download(pin)).status_code == 404
