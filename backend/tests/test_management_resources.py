"""Management grants, tenant isolation, shared lifecycles and durable receipts."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from test_experts import content
from test_identity_access import env as identity_environment
from test_management_cli import bearer, client, identity, login  # noqa: F401
from test_skills import package, payload

from app.modules.management.models import ManagementCommand
from app.modules.members.models import Membership
from app.modules.skills.models import Skill
from app.modules.tenants.models import Tenant

env = identity_environment
pytestmark = pytest.mark.asyncio
WRITE = "management:read management:write"


def headers(tokens, request_id=None):
    return {**bearer(tokens), "X-Management-Request-ID": str(request_id or uuid4())}


async def test_readonly_grant_cannot_mutate_and_write_is_explicit(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        readonly, _ = await login(env, monkeypatch, api, web)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        response = await api.post(
            root + "/skills/import", json=payload(), headers=headers(readonly)
        )
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "insufficient_scope"
        assert (await api.get(root + "/skills", headers=bearer(readonly))).status_code == 200
        writable, _ = await login(env, monkeypatch, api, web, WRITE)
        assert writable["scope"] == WRITE
        assert (await api.get("/api/v1/management/me", headers=bearer(writable))).json()[
            "scope"
        ] == WRITE
        assert (await api.get("/api/v1/management/me", headers=bearer(readonly))).json()[
            "scope"
        ] == "management:read"
        permissions = (await api.get(root + "/permissions", headers=bearer(writable))).json()[
            "permissions"
        ]
        assert {"skills.write", "mcp.write", "experts.write"}.issubset(permissions)
        assert (
            await api.post(root + "/skills/import", json=payload(), headers=bearer(writable))
        ).status_code == 422
        async with env.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(ManagementCommand)) == 0


async def test_skill_lifecycle_matches_web_and_published_draft_cannot_be_deleted(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        preview = await api.post(
            root + "/skills/preview", content=package(), headers=bearer(tokens)
        )
        assert preview.status_code == 200, preview.text
        response = await api.post(root + "/skills/import", json=payload(), headers=headers(tokens))
        assert response.status_code == 200, response.text
        skill = response.json()["result"]
        assert (await web.api.get("/api/v1/skills/" + skill["id"])).json() == skill
        version = skill["versions"][0]["id"]
        path = root + f"/skills/{skill['id']}/versions/{version}"
        assert (await api.get(path + "/overview", headers=bearer(tokens))).status_code == 200
        published = await api.post(
            path + "/actions",
            json={"revision": skill["revision"], "action": "publish"},
            headers=headers(tokens),
        )
        assert published.status_code == 200, published.text
        skill = published.json()["result"]
        assert skill["default_version_id"] == version
        response = await api.delete(
            path, params={"revision": skill["revision"]}, headers=headers(tokens)
        )
        assert response.status_code == 409
        response = await api.post(
            path + "/actions",
            json={"revision": skill["revision"], "action": "withdraw"},
            headers=headers(tokens),
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["default_version_id"] is None


async def test_same_request_replays_once_and_different_body_conflicts(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        request_id = uuid4()
        original_body = payload()
        responses = await asyncio.gather(
            *[
                api.post(
                    root + "/skills/import", json=original_body, headers=headers(tokens, request_id)
                )
                for _ in range(2)
            ]
        )
        successful = [response for response in responses if response.status_code == 200]
        assert successful, [response.text for response in responses]
        for response in responses:
            assert response.status_code in {200, 409}, response.text
            if response.status_code == 409:
                assert response.json()["error"]["code"] == "command_unconfirmed"
        replay = await api.post(
            root + "/skills/import", json=original_body, headers=headers(tokens, request_id)
        )
        assert replay.status_code == 200, replay.text
        assert replay.json() == successful[0].json()
        changed = dict(original_body)
        changed["description"] = "Different description"
        assert (
            await api.post(
                root + "/skills/import", json=changed, headers=headers(tokens, request_id)
            )
        ).status_code == 409
        receipt = await api.get(root + f"/commands/{request_id}", headers=bearer(tokens))
        assert receipt.json()["result"]["status"] == "succeeded"
        assert receipt.json()["result"]["result"] == successful[0].json()
        async with env.sessions() as db:
            assert await db.scalar(select(func.count()).select_from(Skill)) == 1


async def test_replay_and_receipt_require_current_role(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        request_id = uuid4()
        assert (
            await api.post(
                root + "/skills/import", json=payload(), headers=headers(tokens, request_id)
            )
        ).status_code == 200
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.role = "member"
            await db.commit()
        assert (
            await api.post(
                root + "/skills/import", json=payload(), headers=headers(tokens, request_id)
            )
        ).status_code == 403
        assert (
            await api.get(root + f"/commands/{request_id}", headers=bearer(tokens))
        ).status_code == 403


async def test_foreign_org_resources_and_receipts_are_not_visible(env, monkeypatch):
    web = await env.client()
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        other = Tenant(name="Another organization")
        db.add(other)
        await db.flush()
        db.add(
            Membership(
                tenant_id=other.id, user_id=web.user.id, role="administrator", source="invitation"
            )
        )
        await db.commit()
    async with client(env) as api:
        tokens, _ = await login(
            env, monkeypatch, api, web, WRITE, [str(web.tenant.id), str(other.id)]
        )
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        second = f"/api/v1/management/organizations/{other.id}"
        request_id = uuid4()
        skill = (
            await api.post(
                root + "/skills/import", json=payload(), headers=headers(tokens, request_id)
            )
        ).json()["result"]
        assert (
            await api.get(second + "/skills/" + skill["id"], headers=bearer(tokens))
        ).status_code == 404
        assert (
            await api.get(second + f"/commands/{request_id}", headers=bearer(tokens))
        ).status_code == 404
        response = await api.post(
            second + "/experts",
            json={
                "content": content(
                    skills=[
                        {
                            "key": "skill",
                            "skill_id": skill["id"],
                            "version_id": skill["versions"][0]["id"],
                            "sha256": skill["versions"][0]["sha256"],
                            "required": True,
                        }
                    ]
                )
            },
            headers=headers(tokens),
        )
        assert response.status_code in {404, 422}, response.text
        assert (await api.get(second + "/skills", headers=bearer(tokens))).json()["result"][
            "items"
        ] == []


async def test_mcp_configuration_and_expert_publication_share_web_state(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        response = await api.post(
            root + "/mcp/services",
            json={"name": "Managed tool", "transport": "builtin"},
            headers=headers(tokens),
        )
        assert response.status_code == 200, response.text
        mcp = response.json()["result"]
        assert mcp["enabled"] is False
        assert (await web.api.get("/api/v1/mcp/services")).json()["items"][0]["id"] == mcp["id"]
        response = await api.post(
            root + "/experts", json={"content": content()}, headers=headers(tokens)
        )
        assert response.status_code == 200, response.text
        expert = response.json()["result"]
        assert expert["check"]["can_publish"]
        body = {"revision": expert["revision"], "version": "1.0.0"}
        request_id = uuid4()
        response = await api.post(
            root + f"/experts/{expert['id']}/publish",
            json=body,
            headers=headers(tokens, request_id),
        )
        assert response.status_code == 200, response.text
        assert (
            await api.post(
                root + f"/experts/{expert['id']}/publish",
                json=body,
                headers=headers(tokens, request_id),
            )
        ).json() == response.json()
        published = (await web.api.get("/api/v1/experts/" + expert["id"])).json()
        assert len(published["releases"]) == 1
        body = {"revision": published["revision"]}
        assert (
            await api.post(
                root + f"/experts/{expert['id']}/withdraw", json=body, headers=headers(tokens)
            )
        ).status_code == 200


async def test_resource_validation_does_not_echo_secrets(env, monkeypatch):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        secret = "test-only-sensitive-value"
        response = await api.post(
            root + "/mcp/services",
            json={"name": "Invalid", "transport": secret, "credential_values": {"token": secret}},
            headers=headers(tokens),
        )
        assert response.status_code == 422
        assert secret not in response.text


async def test_existing_web_csrf_protection_is_preserved(env):
    web = await env.client()
    for path, body in [
        ("/api/v1/skills/import", payload()),
        ("/api/v1/mcp/services", {"name": "Test", "transport": "builtin"}),
        ("/api/v1/experts", {"content": content()}),
    ]:
        response = await web.api.post(path, json=body, headers={"x-csrf-token": "wrong"})
        assert response.status_code == 403, response.text


async def test_mcp_delete_requires_current_version_and_receipts_never_store_credentials(
    env, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.modules.mcp import network

    env.provider.settings.mcp_public_dns = "cloudflare"
    monkeypatch.setattr(network, "public_dns", AsyncMock(return_value=["1.0.0.1"]))
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        request_id = uuid4()
        secret = "fixture-only-credential"
        response = await api.post(
            root + "/mcp/services",
            json={
                "name": "Protected tool",
                "transport": "http",
                "url": "https://example.com/mcp",
                "auth_mode": "organization",
                "credential_fields": [
                    {"key": "token", "label": "Token", "header": "Authorization", "bearer": True}
                ],
                "credential_values": {"token": secret},
            },
            headers=headers(tokens, request_id),
        )
        assert response.status_code == 200, response.text
        row = response.json()["result"]
        receipt = await api.get(root + f"/commands/{request_id}", headers=bearer(tokens))
        assert secret not in response.text + receipt.text
        async with env.sessions() as db:
            command = await db.get(ManagementCommand, (web.tenant.id, web.user.id, request_id))
            assert secret not in str(command.result)
        path = root + f"/mcp/services/{row['id']}"
        assert (await api.delete(path, headers=headers(tokens))).status_code == 422
        assert (
            await api.delete(path, params={"version": row["version"] + 1}, headers=headers(tokens))
        ).status_code == 409
        assert (
            await api.delete(path, params={"version": row["version"]}, headers=headers(tokens))
        ).status_code == 200
        assert (await api.get(root + "/mcp/services", headers=bearer(tokens))).json()["result"][
            "items"
        ] == []


async def test_uncertain_operation_is_recorded_and_never_dispatched_again(env, monkeypatch):
    from fastapi import HTTPException

    from app.modules.management import mcp_dispatch as operations

    calls = 0

    async def interrupted(**kwargs):
        nonlocal calls
        calls += 1
        raise HTTPException(502, "Remote response unavailable")

    monkeypatch.setattr(operations, "discover", interrupted)
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        path = root + f"/mcp/services/{uuid4()}/discover"
        request_id = uuid4()
        assert (await api.post(path, headers=headers(tokens, request_id))).status_code == 502
        assert (await api.post(path, headers=headers(tokens, request_id))).status_code == 409
        assert calls == 1
        receipt = (await api.get(root + f"/commands/{request_id}", headers=bearer(tokens))).json()[
            "result"
        ]
        assert receipt["status"] == "unknown"
        assert receipt["result"] is None


async def test_write_grant_refresh_is_preserved_and_normal_member_is_not_an_administrator(
    env, monkeypatch
):
    web = await env.client()
    async with client(env) as api:
        tokens, _ = await login(env, monkeypatch, api, web, WRITE)
        async with env.sessions() as db:
            member = await db.get(Membership, web.member.id)
            member.role = "member"
            await db.commit()
        response = await api.post(
            "/api/v1/management/refresh",
            json={
                "refresh_token": tokens["refresh_token"],
                "request_id": str(uuid4()),
                "recovery_version": 2,
            },
        )
        assert response.status_code == 200, response.text
        tokens = response.json()
        assert tokens["scope"] == WRITE
        root = f"/api/v1/management/organizations/{web.tenant.id}"
        for kind in ["skills", "mcp/services", "experts"]:
            assert (await api.get(root + "/" + kind, headers=bearer(tokens))).status_code == 403
        assert (
            await api.post(root + "/skills/import", json=payload(), headers=headers(tokens))
        ).status_code == 403
