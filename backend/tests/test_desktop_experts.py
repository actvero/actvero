from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from test_desktop import bearer, login, native_client
from test_desktop_mcp import token
from test_desktop_skills import create as create_skill
from test_experts import BASE as ADMIN
from test_experts import content, create, publish
from test_identity_access import env as env
from test_mcp import create as create_connector
from test_mcp import update as update_connector
from test_mcp import upstream as upstream

from app.modules.desktop.oidc import NativeIdentity
from app.modules.experts.models import ExpertRelease
from app.modules.mcp import network
from app.modules.members.models import Membership
from app.modules.skills.models import Skill

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/desktop/experts"


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


async def native(env, monkeypatch, api, user):
    root, _ = await login(env, monkeypatch, api, user)
    return root, bearer(await token(api, root, "experts:catalog"))


def proof(e):
    return {"release_id": e["current_release"]["id"], "sha256": e["current_release"]["sha256"]}


async def scope(admin, e, audience="organization", member_ids=None):
    r = await admin.api.put(
        ADMIN + "/" + e["id"] + "/scope",
        json={"revision": e["revision"], "audience": audience, "member_ids": member_ids or []},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_categories_are_authoritative_mutable_and_counts_are_authorized(env, monkeypatch):
    admin, alice, bob = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    added = (await admin.api.post(ADMIN + "/categories", json={"name": "团队自定义"})).json()
    c = next(c for c in added if c["name"] == "团队自定义")
    e = await publish(admin, await create(admin, category=c["id"]))
    e = await scope(admin, e, "selected", [str(alice.member.id)])
    await create(admin, category=c["id"])
    async with native_client(env) as api:
        for user, expected in ((alice, 1), (bob, 0), (admin, 0)):
            _, headers = await native(env, monkeypatch, api, user)
            catalog = (await api.get(BASE, headers=headers)).json()
            assert catalog["total"] == expected
            cats = (await api.get(BASE + "/categories", headers=headers)).json()
            assert [r["id"] for r in cats] == [r["id"] for r in added]
            assert next(r for r in cats if r["id"] == c["id"])["count"] == expected
            if not expected:
                assert (await api.get(BASE + "/" + e["id"], headers=headers)).status_code == 404
        _, headers = await native(env, monkeypatch, api, alice)
        before = (await api.get(BASE + "/" + e["id"], headers=headers)).json()
        assert before["manifest"]["category"] == "general"
        await admin.api.patch(
            ADMIN + "/categories/" + c["id"], json={"name": "客户成功", "revision": 1}
        )
        updates = (
            await api.post(
                BASE + "/check-updates",
                headers=headers,
                json={"items": [{"expert_id": e["id"], **proof(e)}]},
            )
        ).json()["items"][0]
        assert updates["status"] == "current"
        assert updates["expert"]["category"]["name"] == "客户成功"
        assert updates["expert"]["metadata_revision"] > before["metadata_revision"]
        assert (await api.get(BASE + "/categories?q=不匹配", headers=headers)).json()[-2][
            "count"
        ] == 0


async def test_exact_release_races_drafts_and_withdrawal(env, monkeypatch):
    admin = await env.client()
    e = await publish(admin, await create(admin))
    async with native_client(env) as api:
        _, headers = await native(env, monkeypatch, api, admin)
        old = proof(e)
        assert (
            await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=old)
        ).json()["can_prepare"]
        e = (
            await admin.api.put(
                ADMIN + "/" + e["id"],
                json={"revision": e["revision"], "content": content(name="未发布名称")},
            )
        ).json()
        assert (await api.get(BASE + "?q=未发布名称", headers=headers)).json()["total"] == 0
        assert (await api.get(BASE + "/" + e["id"], headers=headers)).json()["name"] == "周报专家"
        e = await publish(admin, e, "2.0.0")
        conflict = await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=old)
        assert (
            conflict.status_code == 409
            and conflict.json()["error"]["code"] == "expert_release_changed"
        )
        await admin.api.post(ADMIN + "/" + e["id"] + "/withdraw", json={"revision": e["revision"]})
        assert (await api.get(BASE + "/" + e["id"], headers=headers)).status_code == 404


async def test_expert_permission_never_grants_skill_permission_and_no_leak(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    s, _ = await create_skill(admin, audience="administrators")
    v = s["versions"][0]
    e = await publish(
        admin,
        await create(
            admin,
            content=content(
                skills=[
                    {
                        "key": "secret",
                        "label": "所需技能",
                        "required": True,
                        "load": "always",
                        "skill_id": s["id"],
                        "version_id": v["id"],
                        "sha256": v["sha256"],
                    }
                ]
            ),
        ),
    )
    e = await scope(admin, e)
    async with native_client(env) as api:
        _, headers = await native(env, monkeypatch, api, member)
        r = await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
        assert r.status_code == 200
        assert not r.json()["can_prepare"]
        assert r.json()["dependencies"] == [
            {
                "kind": "skills",
                "key": "secret",
                "required": True,
                "status": "unavailable",
                "action": "contact_admin",
            }
        ]
        async with env.sessions() as db:
            row = await db.get(Skill, UUID(s["id"]))
            row.audience = "organization"
            await db.commit()
        r = await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
        assert r.json()["can_prepare"]
        assert r.json()["dependencies"][0]["version_id"] == v["id"]
        async with env.sessions() as db:
            row = await db.get(Skill, UUID(s["id"]))
            row.default_version_id = None
            await db.commit()
        assert not (
            await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
        ).json()["can_prepare"]


@pytest.mark.parametrize(
    "auth_mode,required,status,can_prepare",
    [
        ("personal", True, "connection_required", False),
        ("personal", False, "connection_required", True),
        ("none", True, "unverified", False),
    ],
)
async def test_mcp_personal_connection_and_unverified_are_truthful(
    env, monkeypatch, auth_mode, required, status, can_prepare
):
    # This tests dependency state, not public DNS availability. URL validation
    # still receives a public address; no upstream discovery is performed.
    env.provider.settings.mcp_public_dns = "cloudflare"
    monkeypatch.setattr(network, "public_dns", AsyncMock(return_value=["1.0.0.1"]))
    admin = await env.client()
    service = await create_connector(
        admin,
        auth_mode=auth_mode,
        transport="http",
        url="https://example.com/mcp",
        credential_fields=[
            {"key": "token", "label": "Token", "header": "Authorization", "bearer": True}
        ]
        if auth_mode == "personal"
        else [],
    )
    service = await update_connector(admin, service, enabled=True)
    e = await publish(
        admin,
        await create(
            admin,
            content=content(
                connectors=[
                    {
                        "key": "notes",
                        "label": "资料",
                        "required": required,
                        "connector_id": service["id"],
                    }
                ]
            ),
        ),
    )
    async with native_client(env) as api:
        _, headers = await native(env, monkeypatch, api, admin)
        r = await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
        assert r.status_code == 200, r.text
        assert r.json()["can_prepare"] is can_prepare
        assert r.json()["dependencies"][0]["status"] == status
        assert r.json()["dependencies"][0]["action"] == (
            "configure" if auth_mode == "personal" else "contact_admin"
        )


async def test_token_scopes_native_boundary_and_revocation(env, monkeypatch):
    admin = await env.client()
    e = await publish(admin, await create(admin))
    async with native_client(env) as api:
        root, headers = await native(env, monkeypatch, api, admin)
        assert (await api.get(BASE, headers=bearer(root))).status_code == 401
        assert (await admin.api.get(BASE, headers=headers)).status_code == 401
        assert (await api.get("/api/v1/desktop/skills", headers=headers)).status_code == 403
        assert (await api.get("/api/v1/desktop/mcp/connectors", headers=headers)).status_code == 403
        assert (await api.get(ADMIN, headers=headers)).status_code == 401
        skills = bearer(await token(api, root, "skills:catalog"))
        assert (await api.get(BASE, headers=skills)).status_code == 403
        async with env.sessions() as db:
            m = await db.get(Membership, admin.member.id)
            m.status = "paused"
            await db.commit()
        assert (
            await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
        ).status_code == 403


async def test_release_digest_is_deterministic_and_contains_no_platform_metadata(env):
    from app.modules.experts.models import ExpertRecord
    from app.modules.experts.schemas import ExpertContent
    from app.modules.experts.service import release_payload

    admin = await env.client()
    e = await publish(admin, await create(admin))
    async with env.sessions() as db:
        row = await db.get(ExpertRecord, UUID(e["id"]))
        release = await db.get(ExpertRelease, UUID(e["current_release"]["id"]))
        manifest, refs, sha = release_payload(row, ExpertContent.model_validate(row.draft), "1.0.0")
        assert sha == release.sha256
        assert manifest == release.manifest and refs == release.dependency_refs
        assert not {"tenant_id", "member_ids", "revision", "workspace", "token"}.intersection(
            manifest
        )


async def test_expert_tools_filter_gateway_and_preserve_source_policy(env, monkeypatch, upstream):
    import hashlib
    import json

    import httpx2
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, member = await env.client(), await env.client(role="member")
    connector = await create_connector(admin, transport=transport, url=url)
    path = "/api/v1/mcp/services/" + connector["id"]
    assert (await admin.api.post(path + "/discover")).status_code == 200
    connector = await update_connector(admin, connector, enabled=True)
    ref = {
        "key": "lab",
        "label": "测试连接器",
        "required": True,
        "connector_id": connector["id"],
        "tools": ["add"],
    }
    e = await scope(
        admin, await publish(admin, await create(admin, content=content(connectors=[ref])))
    )
    # Metadata uses the current actor's discovery; members cannot read admin configuration.
    detail_path = ADMIN + "/dependencies/connectors/" + connector["id"]
    details = (await admin.api.get(detail_path)).json()
    assert {t["key"] for t in details["tools"]} == {"add", "caller"}
    assert details["tools_discovered"]
    assert (await member.api.get(detail_path)).status_code == 403
    for invalid in (["unknown"], ["add", "add"], ["bad\0name"]):
        assert (
            await admin.api.post(
                ADMIN, json={"content": content(connectors=[{**ref, "tools": invalid}])}
            )
        ).status_code == 422

    async with native_client(env) as api:
        root, headers = await native(env, monkeypatch, api, member)
        envelope = (await api.get(BASE + "/" + e["id"], headers=headers)).json()
        assert envelope["contract_version"] == 3
        assert envelope["manifest"]["connectors"] == [
            {"key": "lab", "label": "测试连接器", "required": True}
        ]
        canonical = json.dumps(
            {k: envelope[k] for k in ("manifest", "dependency_refs")},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        assert hashlib.sha256(canonical.encode()).hexdigest() == e["current_release"]["sha256"]
        resolved = (
            await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
        ).json()
        dependency = resolved["dependencies"][0]
        assert dependency["tools"] == ["add"]
        invocation = await token(api, root, "mcp:" + connector["id"])

        def factory(**kwargs):
            return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=env.app), **kwargs)

        def gateway(endpoint):
            return StreamableHttpTransport(
                endpoint, headers=bearer(invocation), httpx_client_factory=factory
            )

        async with Client(
            gateway(dependency["mcp_endpoint"]), mode="legacy", timeout=10, cache=False
        ) as client:
            assert [t.name for t in await client.list_tools()] == ["add"]
            assert "5" in str(await client.call_tool("add", {"a": 2, "b": 3}))
            with pytest.raises(Exception, match="未启用"):
                await client.call_tool("caller", {})
            assert [p.name for p in await client.list_prompts()] == ["greet"]
            # Editing/publishing an empty allowlist does not change an existing release.
            saved = await admin.api.put(
                ADMIN + "/" + e["id"],
                json={
                    "revision": e["revision"],
                    "content": content(connectors=[{**ref, "tools": []}]),
                },
            )
            assert saved.status_code == 200, saved.text
            e = await publish(admin, saved.json(), "2.0.0")
            assert [t.name for t in await client.list_tools()] == ["add"]
            new_resolution = (
                await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
            ).json()
            async with Client(
                gateway(new_resolution["dependencies"][0]["mcp_endpoint"]),
                mode="legacy",
                timeout=10,
                cache=False,
            ) as empty_client:
                assert await empty_client.list_tools() == []
                with pytest.raises(Exception, match="未启用"):
                    await empty_client.call_tool("add", {"a": 2, "b": 3})
            async with Client(
                gateway(invocation["endpoint"]), mode="legacy", timeout=10, cache=False
            ) as source:
                assert {t.name for t in await source.list_tools()} == {"add", "caller"}
            # Source closure wins over selected tools, and cannot be newly selected.
            await admin.api.put(
                path + "/policy", json={"kind": "tools", "key": "add", "enabled": False}
            )
            assert await client.list_tools() == []
            with pytest.raises(Exception, match="未开放"):
                await client.call_tool("add", {"a": 2, "b": 3})
            invalid = await admin.api.post(ADMIN, json={"content": content(connectors=[ref])})
            assert invalid.status_code == 422
            # Live expert authorization applies even while source is still available.
            e = await scope(admin, e, "administrators")
            with pytest.raises(Exception, match="404|Not Found"):
                await client.list_tools()


async def test_deleted_expert_disappears_and_old_connector_endpoint_is_denied(env, monkeypatch):
    admin = await env.client()
    connector = await update_connector(admin, await create_connector(admin), enabled=True)
    e = await publish(
        admin,
        await create(
            admin,
            content=content(
                connectors=[
                    {
                        "key": "notes",
                        "label": "资料",
                        "connector_id": connector["id"],
                    }
                ]
            ),
        ),
    )
    async with native_client(env) as api:
        root, headers = await native(env, monkeypatch, api, admin)
        resolved = (
            await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
        ).json()
        endpoint = resolved["dependencies"][0]["mcp_endpoint"]
        invocation = await token(api, root, "mcp:" + connector["id"])
        rpc_headers = {**bearer(invocation), "accept": "application/json, text/event-stream"}
        ping = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}
        assert (await api.post(endpoint, headers=rpc_headers, json=ping)).status_code == 200
        assert (
            await admin.api.request(
                "DELETE", ADMIN + "/" + e["id"], json={"revision": e["revision"]}
            )
        ).status_code == 200
        assert (await api.get(BASE, headers=headers)).json()["total"] == 0
        assert (await api.get(BASE + "/" + e["id"], headers=headers)).status_code == 404
        assert (
            await api.post(BASE + "/" + e["id"] + "/resolve", headers=headers, json=proof(e))
        ).status_code == 404
        updates = await api.post(
            BASE + "/check-updates",
            headers=headers,
            json={"items": [{"expert_id": e["id"], **proof(e)}]},
        )
        assert updates.json()["items"][0]["status"] == "unavailable"
        assert (await api.post(endpoint, headers=rpc_headers, json=ping)).status_code == 404
        assert (
            await api.post(invocation["endpoint"], headers=rpc_headers, json=ping)
        ).status_code == 200
