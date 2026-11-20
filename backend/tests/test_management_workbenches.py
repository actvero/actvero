"""Management CLI authorization and shared workbench release behavior."""

from uuid import uuid4

import pytest
from test_desktop import bearer as desktop_bearer
from test_desktop import login as desktop_login
from test_desktop import native_client
from test_desktop_mcp import token as resource_token
from test_identity_access import env as identity_environment
from test_management_cli import bearer, client, identity, login  # noqa: F401
from test_management_resources import WRITE, headers
from test_workbenches import BINARY, package

from app.modules.members.models import Membership
from app.modules.tenants.models import PlatformOperator

env = identity_environment
pytestmark = pytest.mark.asyncio


async def test_workbench_release_and_update_share_web_state_and_replay_upload(env, monkeypatch):
    web = await env.client()
    org_root = f"/api/v1/management/organizations/{web.tenant.id}"
    root = org_root + "/workbenches"
    async with client(env) as api:
        readonly, _ = await login(env, monkeypatch, api, web)
        permissions = (await api.get(org_root + "/permissions", headers=bearer(readonly))).json()
        assert "workbenches.read" in permissions["permissions"]
        assert "workbenches.write" not in permissions["permissions"]
        assert (
            await api.post(root, content=package(), headers=headers(readonly) | BINARY)
        ).status_code == 403
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        permissions = (await api.get(org_root + "/permissions", headers=bearer(tokens))).json()
        assert {"workbenches.read", "workbenches.write"} <= set(permissions["permissions"])
        upload_headers = headers(tokens) | BINARY
        archive = package()
        created = await api.post(root, content=archive, headers=upload_headers)
        assert created.status_code == 201, created.text
        draft = created.json()["result"]
        workbench_id = draft["id"]
        assert draft["status"] == "draft"
        assert (
            await api.post(root, content=archive, headers=upload_headers)
        ).json() == created.json()
        wrong_payload = await api.post(root, content=package("1.0.1"), headers=upload_headers)
        assert wrong_payload.status_code == 409
        assert wrong_payload.json()["error"]["code"] == "command_conflict"
        receipt_path = f"{org_root}/commands/{created.json()['request_id']}"
        receipt = await api.get(receipt_path, headers=bearer(tokens))
        assert receipt.json()["result"]["status"] == "succeeded"
        path = f"{root}/{workbench_id}"
        releases = f"{path}/versions"
        first = draft["versions"][0]["id"]
        published = await api.post(
            f"{releases}/{first}/publish",
            json={"revision": draft["revision"]},
            headers=headers(tokens),
        )
        assert published.status_code == 200, published.text
        current = published.json()["result"]
        assert current["current_version"] == "1.0.0"

        field = {"key": "SERVICE_URL", "label": "服务地址", "kind": "url", "required": True}
        version = await api.post(
            releases,
            params={"revision": current["revision"]},
            content=package("1.1.0", fields=[field]),
            headers=headers(tokens) | BINARY,
        )
        assert version.status_code == 201, version.text
        updated = version.json()["result"]
        assert updated["current_version"] == "1.0.0"
        candidate = next(item["id"] for item in updated["versions"] if item["version"] == "1.1.0")
        publish_path = f"{releases}/{candidate}/publish"
        for revision in (current["revision"], updated["revision"]):
            assert (
                await api.post(publish_path, json={"revision": revision}, headers=headers(tokens))
            ).status_code == 409

        configured = await api.put(
            f"{path}/runtime-config",
            json={
                "revision": updated["revision"],
                "version_id": candidate,
                "values": {"SERVICE_URL": "https://example.com"},
            },
            headers=headers(tokens),
        )
        assert configured.status_code == 200, configured.text
        release = await api.post(
            publish_path,
            json={"revision": configured.json()["result"]["revision"], "release_notes": "升级"},
            headers=headers(tokens),
        )
        assert release.status_code == 200, release.text
        live = release.json()["result"]
        assert live["current_version"] == "1.1.0"
        assert {item["version"]: item["status"] for item in live["versions"]} == {
            "1.0.0": "superseded",
            "1.1.0": "published",
        }
        assert (await web.api.get(f"/api/v1/workbenches/{workbench_id}")).json() == live

        async with native_client(env) as desktop:
            session, _ = await desktop_login(env, monkeypatch, desktop, web)
            app_headers = desktop_bearer(
                await resource_token(desktop, session, "workbenches:config")
            )
            catalog = await desktop.get("/api/v1/desktop/workbenches", headers=app_headers)
            assert catalog.status_code == 200, catalog.text
            assert [item["version_id"] for item in catalog.json()["items"]] == [candidate]
            update = await desktop.post(
                "/api/v1/desktop/workbenches/check-updates",
                json={
                    "workbench_id": workbench_id,
                    "version_id": first,
                    "sha256": draft["versions"][0]["sha256"],
                },
                headers=app_headers,
            )
            assert update.json() == {"status": "update_available", "adopted_usable": True}

        listed = await api.get(root, params={"status": "published"}, headers=bearer(tokens))
        assert [item["id"] for item in listed.json()["result"]["items"]] == [workbench_id]
        foreign = f"/api/v1/management/organizations/{uuid4()}/workbenches/{workbench_id}"
        assert (await api.get(foreign, headers=bearer(tokens))).status_code == 403

        env.provider.settings.platform_edition = "saas"
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.source, member.role = "platform", "member"
            db.add(PlatformOperator(user_id=web.user.id, status="active"))
            await db.commit()
        assert (await api.get(org_root + "/channels", headers=bearer(tokens))).status_code == 200
        assert (await api.get(path, headers=bearer(tokens))).status_code == 403
        assert (await api.get(receipt_path, headers=bearer(tokens))).status_code == 404


async def test_workbench_upload_rejects_oversized_binary_without_a_receipt(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        request_id = uuid4()
        response = await api.post(
            root + "/workbenches",
            content=b"x" * (8 * 1024 * 1024 + 1),
            headers=headers(tokens, request_id) | BINARY,
        )
        assert response.status_code == 413, response.text
        receipt = await api.get(f"{root}/commands/{request_id}", headers=bearer(tokens))
        assert receipt.status_code == 404
