"""Test application identity, live permissions and reuse of model settlement."""

from uuid import UUID

import pytest
from sqlalchemy import text
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model
from test_llm_execution import configured, payload, upstream
from test_llm_routing import update as update_model
from test_mcp import listening
from test_mcp import upstream as mcp_fixture

from app.modules.auth.models import WebSession
from app.modules.integrations.models import IntegrationKey
from app.modules.llm.models import ModelCall, UsageSettlement
from app.modules.members.models import Membership
from app.modules.tenants.models import Tenant

env = identity_env
mcp_upstream = mcp_fixture
pytestmark = pytest.mark.asyncio
APPS = "/api/v1/integrations/applications"
ME = "/api/integrations/v1/me"
LLM = "/api/llm/v1"


def bearer(body):
    return {"Authorization": "Bearer " + body["secret"]}


async def create_key(admin, app, name):
    response = await admin.api.post(f"{APPS}/{app['id']}/keys", json={"name": name})
    assert response.status_code == 201, response.text
    assert response.headers["Cache-Control"] == "no-store"
    return response.json()


async def test_application_discovery_invocation_and_key_rotation(env):
    admin, operator, member = (
        await env.client(),
        await env.client(),
        await env.client(role="member"),
    )
    assert (await member.api.get(APPS)).status_code == 403
    assert (
        await admin.api.post(APPS, json={"name": "Odoo"}, headers={"x-csrf-token": "invalid"})
    ).status_code == 403
    server, observed = upstream()
    async with listening(server) as base, native_client(env) as api:
        model, _ = await configured(env, admin, base)
        creation = await admin.api.post(APPS, json={"name": "Odoo"})
        assert creation.status_code == 201, creation.text
        app = creation.json()
        path = f"{APPS}/{app['id']}"
        first = await create_key(admin, app, "Primary")
        headers = bearer(first)
        assert first["secret"] not in (await admin.api.get(path + "/keys")).text
        async with env.sessions() as db:
            stored = await db.get(IntegrationKey, UUID(first["key"]["id"]))
            assert stored and first["secret"] not in str(stored.__dict__)
            creator = await db.get(Membership, admin.member.id)
            creator.status = "removed"
            await db.commit()
        connection = (await api.get(ME, headers=headers)).json()
        assert connection["application_id"] == app["id"] and not connection["models_enabled"]
        assert (await api.get(APPS, headers=headers)).status_code == 401
        assert (
            await api.get(ME, headers={**headers, "Origin": "https://example.com"})
        ).status_code == 401
        catalog = await api.get(LLM + "/models", headers=headers)
        assert catalog.status_code == 403, catalog.text
        url = LLM + "/chat/completions"
        assert (await api.post(url, json=payload(model), headers=headers)).status_code == 403
        assert not observed["calls"]
        changes = {
            "version": app["version"],
            "enabled": True,
            "name": app["name"],
            "models_enabled": True,
        }
        updated = await operator.api.put(path, json=changes)
        assert updated.status_code == 200, updated.text
        assert (await operator.api.put(path, json=changes)).status_code == 409
        catalog = await api.get(LLM + "/models", headers=headers)
        assert catalog.status_code == 200, catalog.text
        assert {m["id"] for m in catalog.json()["data"]} == {model["slug"]}
        response = await api.post(
            url, json=payload(model), headers={**headers, "Idempotency-Key": "odoo-1"}
        )
        assert response.status_code == 200, response.text
        assert len(observed["calls"]) == 1
        entries = (await operator.api.get(path + "/calls")).json()["items"]
        assert len(entries) == 1 and entries[0]["member_name"] == app["name"]
        assert entries[0]["settlement_status"] == "settled" and entries[0]["amount"] is not None
        call_id = entries[0]["id"]
        async with env.sessions() as db:
            call = await db.get(ModelCall, UUID(call_id))
            settlement = await db.get(UsageSettlement, UUID(call_id))
            assert call and call.actor_id is None and str(call.application_id) == app["id"]
            assert settlement and settlement.member_id is None and settlement.ratio is None
        second = await create_key(operator, app, "Replacement")
        assert (await operator.api.delete(path + "/keys/" + first["key"]["id"])).status_code == 204
        assert (await api.get(ME, headers=headers)).status_code == 401
        replacement = bearer(second)
        duplicate = await api.post(
            url, json=payload(model), headers={**replacement, "Idempotency-Key": "odoo-1"}
        )
        assert duplicate.status_code == 409 and call_id in duplicate.text
        assert len(observed["calls"]) == 1
        receipt = await api.get("/api/integrations/v1/calls/" + call_id, headers=replacement)
        assert receipt.json()["settlement_status"] == "settled"

        future = await create_model(
            operator,
            name="Later model",
            slug="later-chat",
            access=model["access"],
            bindings=[{k: v for k, v in b.items() if k != "binding_id"} for b in model["bindings"]],
            context_window=model["context_window"],
            max_output=model["max_output"],
            budget_price=model["budget_price"],
        )
        catalog = await api.get(LLM + "/models", headers=replacement)
        assert {m["id"] for m in catalog.json()["data"]} == {model["slug"], future["slug"]}
        assert (await api.post(url, json=payload(future), headers=replacement)).status_code == 200
        await update_model(operator, future, access={**future["access"], "enabled": False})
        assert (await api.post(url, json=payload(future), headers=replacement)).status_code == 404

        closed = await operator.api.put(
            path, json={**changes, "version": updated.json()["version"], "models_enabled": False}
        )
        assert closed.status_code == 200, closed.text
        assert (await api.get(ME, headers=replacement)).status_code == 200
        assert (await api.get(LLM + "/models", headers=replacement)).status_code == 403
        assert (await api.post(url, json=payload(model), headers=replacement)).status_code == 403
        assert len(observed["calls"]) == 2
        assert (
            await operator.api.put(
                path,
                json={
                    **changes,
                    "version": closed.json()["version"],
                    "models_enabled": False,
                    "enabled": False,
                },
            )
        ).status_code == 200
        assert (await api.get(ME, headers=replacement)).status_code == 403


async def test_application_tenant_and_receipt_boundaries(env):
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        first_org, second_org = Tenant(name="First"), Tenant(name="Second", instance_slot=None)
        db.add_all([first_org, second_org])
        await db.commit()
    first, second = await env.client(tenant=first_org), await env.client(tenant=second_org)
    async with env.sessions() as db:
        for user in (first, second):
            session = await db.get(WebSession, user.session.id)
            session.tenant_id = user.tenant.id
        await db.commit()
    server, _ = upstream()
    async with listening(server) as base, native_client(env) as api:
        model, _ = await configured(env, first, base)
        foreign = await second.api.post(APPS, json={"name": "External", "models_enabled": True})
        assert foreign.status_code == 201, foreign.text
        foreign_key = bearer(await create_key(second, foreign.json(), "External"))
        catalog = await api.get(LLM + "/models", headers=foreign_key)
        assert catalog.status_code == 200 and not catalog.json()["data"]
        assert (
            await api.post(LLM + "/chat/completions", json=payload(model), headers=foreign_key)
        ).status_code == 404
        app = (await first.api.post(APPS, json={"name": "Odoo", "models_enabled": True})).json()
        key = await create_key(first, app, "App")
        response = await api.post(
            LLM + "/chat/completions", json=payload(model), headers=bearer(key)
        )
        assert response.status_code == 200, response.text
        call_id = (await first.api.get(f"{APPS}/{app['id']}/calls")).json()["items"][0]["id"]
        assert (await second.api.get(f"{APPS}/{app['id']}")).status_code == 404
        assert (await second.api.get(APPS)).json()["total"] == 1
        other = (await first.api.post(APPS, json={"name": "Other"})).json()
        other_key = await create_key(first, other, "Other")
        assert (
            await api.get("/api/integrations/v1/calls/" + call_id, headers=bearer(other_key))
        ).status_code == 404


async def test_application_knowledge_upload_index_retrieve_and_reader(env):
    from uuid import uuid4

    from test_llm_retrieval import configured as embedding_model
    from test_llm_retrieval import upstream as embedding_server

    from app.modules.knowledge.worker import tick

    admin = await env.client()
    server, observed = embedding_server()
    root = "/api/integrations/v1/knowledge/bases"
    async with listening(server) as url, native_client(env) as api:
        model, _ = await embedding_model(env, admin, url, enabled=True)
        app = (await admin.api.post(APPS, json={"name": "Odoo", "knowledge_enabled": True})).json()
        first_key = await create_key(admin, app, "first")
        headers = bearer(first_key)
        assert (await api.get(LLM + "/models", headers=headers)).status_code == 403
        assert (await api.get(root + "/defaults", headers=headers)).json()["models"][0][
            "id"
        ] == model["id"]
        options = {
            "name": "Odoo Manual",
            "retrieval": {"mode": "hybrid", "embedding_model_id": model["id"]},
        }
        create_path = root + f"?creation_id={uuid4()}"
        made = await api.post(create_path, json=options, headers=headers)
        assert made.status_code == 201, made.text
        item = made.json()
        assert (await api.post(create_path, json=options, headers=headers)).json()["id"] == item[
            "id"
        ]
        assert (
            await api.post(create_path, json={**options, "name": "Different"}, headers=headers)
        ).status_code == 409
        path = root + "/" + item["id"]
        assert (
            await api.put(
                path,
                headers=headers,
                json={**options, "name": "Odoo Guide", "version": item["version"]},
            )
        ).status_code == 200
        foreign = (
            await admin.api.post(
                "/api/v1/knowledge",
                json={
                    "name": "Shared",
                    "audience": "organization",
                },
            )
        ).json()
        private = (await admin.api.post("/api/v1/knowledge", json={"name": "Private"})).json()
        listed = (await api.get(root, headers=headers)).json()
        assert {x["id"] for x in listed["items"]} == {foreign["id"], item["id"]}
        assert (await api.get(root + "/" + private["id"], headers=headers)).status_code == 404
        assert (await api.delete(root + "/" + foreign["id"], headers=headers)).status_code == 403
        data = b"Purchase orders require approval from the manager."
        upload_path = path + f"/documents?filename=guide.txt&upload_id={uuid4()}"
        uploaded = await api.post(upload_path, content=data, headers=headers)
        assert uploaded.status_code == 201, uploaded.text
        doc = uploaded.json()
        assert (await api.post(upload_path, content=data, headers=headers)).json()["id"] == doc[
            "id"
        ]
        second_key = await create_key(admin, app, "replacement")
        assert (
            await admin.api.delete(f"{APPS}/{app['id']}/keys/{first_key['key']['id']}")
        ).status_code == 204
        headers = bearer(second_key)
        for _ in range(8):
            if not await tick(env.app):
                break
        doc_path = path + "/documents/" + doc["id"]
        ready = (await api.get(doc_path, headers=headers)).json()
        assert ready["status"] == "ready", ready
        found = await api.post(path + "/search", json={"query": "purchase orders"}, headers=headers)
        assert found.status_code == 200, found.text
        hit = found.json()["items"][0]
        assert len(observed) >= 2 and hit["source_url"] == doc_path + "/source"
        assert (await api.get(hit["source_url"], headers=headers)).content == data
        reference = path + "/citations/" + hit["id"]
        assert (await api.get(reference, headers=headers)).json()["sources"]
        host = "https://example.com"
        reader = (
            await api.post(
                reference + "/reader-session", json={"parent_origin": host}, headers=headers
            )
        ).json()
        reader_headers = {"Authorization": "Bearer " + reader["token"], "X-Knowledge-Parent": host}
        assert (await api.get("/api/v1/knowledge-reader/manifest", headers=reader_headers)).json()[
            "document_id"
        ] == doc["id"]
        calls = (await admin.api.get(f"{APPS}/{app['id']}/calls")).json()
        assert {x["source"] for x in calls["items"]} == {"knowledge_index", "knowledge_search"}
        assert (
            await api.post(
                doc_path + "/rebuild",
                json={"generation_id": ready["generation_id"]},
                headers=headers,
            )
        ).status_code == 200
        assert (await api.delete(doc_path, headers=headers)).status_code == 204
        assert (
            await api.get("/api/v1/knowledge-reader/source", headers=reader_headers)
        ).status_code == 404
        assert (await api.delete(path, headers=headers)).status_code == 204


async def test_application_skills_and_experts_published_pinned_dependencies(env):
    from test_desktop_skills import create as create_skill
    from test_experts import content, create, publish

    admin = await env.client()
    skill, blob = await create_skill(admin)
    private, _ = await create_skill(admin, name="private", audience="administrators")
    version = skill["versions"][0]
    ref = {
        "key": "report",
        "label": "Report",
        "required": True,
        "load": "always",
        "skill_id": skill["id"],
        "version_id": version["id"],
        "sha256": version["sha256"],
    }
    expert = await create(admin, content=content(skills=[ref]))
    mode = await admin.api.put(
        f"/api/v1/experts/{expert['id']}/scope",
        json={"revision": expert["revision"], "audience": "organization"},
    )
    assert mode.status_code == 200, mode.text
    expert = await publish(admin, mode.json())
    app = (await admin.api.post(APPS, json={"name": "Agent", "experts_enabled": True})).json()
    headers = bearer(await create_key(admin, app, "Agent"))
    async with native_client(env) as api:
        root = "/api/integrations/v1"
        path = root + "/experts/" + expert["id"]
        assert (await api.get(root + "/skills", headers=headers)).status_code == 403
        assert (await api.get(root + "/experts", headers=headers)).json()["total"] == 1
        current = (await api.get(path, headers=headers)).json()
        assert current["dependency_refs"]["skills"][0]["sha256"] == version["sha256"]
        release = current["release"]
        proof = {"release_id": release["id"], "sha256": release["sha256"]}
        blocked = await api.post(path + "/resolve", json=proof, headers=headers)
        assert not blocked.json()["can_prepare"]
        enabled = await admin.api.put(
            f"{APPS}/{app['id']}",
            json={
                "name": app["name"],
                "version": app["version"],
                "enabled": True,
                "models_enabled": False,
                "skills_enabled": True,
            },
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["experts_enabled"]
        resolution = await api.post(path + "/resolve", json=proof, headers=headers)
        assert resolution.json()["can_prepare"], resolution.text
        assert (await api.get(root + "/skills", headers=headers)).json()["total"] == 1
        assert (
            await api.get(root + "/skills/" + private["id"], headers=headers)
        ).status_code == 404
        skill_path = root + "/skills/" + skill["id"]
        detail = (await api.get(skill_path, headers=headers)).json()
        file = await api.get(
            skill_path + "/file",
            params={
                "version_id": version["id"],
                "path": detail["entrypoint"],
            },
            headers=headers,
        )
        assert "Read input" in file.json()["content"]
        result = await api.post(
            skill_path + "/download",
            json={
                "version_id": version["id"],
                "sha256": version["sha256"],
                "expert_id": expert["id"],
                "expert_release_id": release["id"],
            },
            headers=headers,
        )
        assert result.content == blob and result.headers["X-Content-SHA256"] == version["sha256"]


async def test_application_mcp_sync_standard_rpc_and_revocation(env, mcp_upstream):
    from test_desktop_experts import proof, scope
    from test_experts import content, publish
    from test_experts import create as create_expert
    from test_mcp import create, update

    base, transport, upstream_url = mcp_upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin = await env.client()
    row = await create(admin, transport=transport, url=upstream_url)
    discovery = await admin.api.post(f"/api/v1/mcp/services/{row['id']}/discover")
    assert discovery.status_code == 200, discovery.text
    row = await update(admin, row, enabled=True)
    expert = await create_expert(
        admin,
        content=content(
            connectors=[
                {
                    "key": "lab",
                    "label": "Lab",
                    "required": True,
                    "connector_id": row["id"],
                    "tools": ["add"],
                }
            ]
        ),
    )
    expert = await scope(admin, await publish(admin, expert))
    app = (
        await admin.api.post(
            APPS, json={"name": "Odoo", "mcp_enabled": True, "experts_enabled": True}
        )
    ).json()
    headers = {
        **bearer(await create_key(admin, app, "Connector")),
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }
    async with native_client(env) as api:
        catalog = await api.get("/api/integrations/v1/mcp/services", headers=headers)
        assert catalog.status_code == 200 and base not in catalog.text
        endpoint = catalog.json()["items"][0]["endpoint"]
        assert endpoint.endswith(row["id"])
        methods = [
            ("tools/list", {}, '"add"'),
            ("tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}}, "5"),
            ("prompts/get", {"name": "greet", "arguments": {"name": "Test"}}, "Hello Test"),
            ("resources/read", {"uri": "fixture://guide"}, "Guide content"),
        ]
        for method, params, expected in methods:
            result = await api.post(
                endpoint,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": params,
                },
            )
            assert result.status_code == 200 and "result" in result.json(), result.text
            assert expected in result.text
        dependency = await api.post(
            f"/api/integrations/v1/experts/{expert['id']}/resolve",
            headers=headers,
            json=proof(expert),
        )
        assert dependency.json()["can_prepare"], dependency.text
        expert_endpoint = dependency.json()["dependencies"][0]["mcp_endpoint"]
        scoped_tools = await api.post(
            expert_endpoint,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        assert [t["name"] for t in scoped_tools.json()["result"]["tools"]] == ["add"]
        rejected = await api.post(
            expert_endpoint,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "caller", "arguments": {}},
            },
        )
        assert rejected.json()["error"]["data"]["code"] == "expert_tool_denied"
        changed = await admin.api.put(
            f"{APPS}/{app['id']}",
            json={
                "name": app["name"],
                "version": app["version"],
                "enabled": True,
                "models_enabled": False,
                "mcp_enabled": False,
            },
        )
        assert changed.status_code == 200
        assert (
            await api.get("/api/integrations/v1/mcp/services", headers=headers)
        ).status_code == 403
        assert (
            await api.post(
                endpoint,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                    "params": {},
                },
            )
        ).status_code == 403
