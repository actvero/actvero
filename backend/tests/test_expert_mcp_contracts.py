"""Real MCP discovery plus immutable selected-schema proofs and late authorization checks."""

import asyncio
import copy
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from test_desktop import bearer, native_client
from test_desktop_experts import native, proof, scope
from test_desktop_mcp import token
from test_experts import BASE as ADMIN
from test_experts import content, create, publish
from test_identity_access import env as env
from test_mcp import create as connector_create
from test_mcp import update as connector_update
from test_mcp import upstream as upstream

from app.modules.desktop.oidc import NativeIdentity
from app.modules.experts.models import ExpertRelease
from app.modules.mcp import service as mcp

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/desktop/experts"


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


async def setup(env, upstream, *, tools=None, required=True, personal=False):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, member = await env.client(), await env.client(role="member")
    config = (
        {
            "auth_mode": "personal",
            "credential_fields": [
                {"key": "token", "label": "Token", "header": "Authorization", "bearer": True}
            ],
        }
        if personal
        else {}
    )
    connector = await connector_create(admin, transport=transport, url=url, **config)
    path = "/api/v1/mcp/services/" + connector["id"]
    if personal:
        assert (
            await admin.api.put(path + "/connection", json={"values": {"token": "person-a"}})
        ).status_code == 200
    assert (await admin.api.post(path + "/discover")).status_code == 200
    connector = await connector_update(admin, connector, enabled=True)
    ref = {
        "key": "lab",
        "label": "Lab",
        "required": required,
        "connector_id": connector["id"],
        "tools": tools if tools is not None else ["add"],
    }
    expert = await scope(
        admin, await publish(admin, await create(admin, content=content(connectors=[ref])))
    )
    return admin, member, connector, expert, path


async def resolution(api, expert, headers, access_version=2):
    response = await api.post(
        BASE + "/" + expert["id"] + "/resolve",
        json={**proof(expert), "access_version": access_version},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def rpc(api, endpoint, credentials, method, params=None):
    return (
        await api.post(
            endpoint,
            headers={
                **bearer(credentials),
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": "2025-03-26",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        )
    ).json()


@pytest.mark.parametrize("change", ["selected_schema", "description", "unselected_schema"])
async def test_only_selected_semantic_changes_invalidate_release(
    env, upstream, monkeypatch, change
):
    admin, member, connector, expert, path = await setup(env, upstream)
    original_discover = mcp.discover
    calls = AsyncMock(wraps=mcp.call_tool)
    monkeypatch.setattr(mcp, "call_tool", calls)
    async with native_client(env) as api:
        root, h = await native(env, monkeypatch, api, member)
        first = await resolution(api, expert, h)
        assert first["can_prepare"]
        endpoint = first["dependencies"][0]["mcp_endpoint"]
        credentials = await token(api, root, "mcp:" + connector["id"])
        envelope = (await api.get(BASE + "/" + expert["id"], headers=h)).json()
        old = envelope["dependency_refs"]["connectors"][0]["tool_contracts"]
        assert set(old) == {"add"} and len(old["add"]) == 64

        async def changed(client):
            data = copy.deepcopy(await original_discover(client))
            for entry in data:
                if entry["kind"] != "tools":
                    continue
                if change == "description":
                    entry["description"] = entry["definition"]["description"] = "New description"
                elif entry["key"] == ("add" if change == "selected_schema" else "caller"):
                    entry["definition"]["inputSchema"]["properties"]["optionalNewField"] = {
                        "type": "string"
                    }
            return data

        monkeypatch.setattr(mcp, "discover", changed)
        assert (await admin.api.post(path + "/discover")).status_code == 200
        # Approving a new source policy cannot change the old expert contract.
        if change == "selected_schema":
            assert (
                await admin.api.put(
                    path + "/policy", json={"kind": "tools", "key": "add", "enabled": True}
                )
            ).status_code == 200
        if change == "selected_schema":
            details = (await admin.api.get(ADMIN + "/" + expert["id"])).json()
            assert details["has_changes"] and details["dependency_issues"] == 1
        state = await resolution(api, expert, h)
        assert state["can_prepare"] == (change != "selected_schema")
        assert state["dependencies"][0]["status"] == (
            "version_conflict" if change == "selected_schema" else "available"
        )
        result = await rpc(
            api, endpoint, credentials, "tools/call", {"name": "add", "arguments": {"a": 2, "b": 3}}
        )
        if change == "selected_schema":
            assert "error" in result and "定义已变化" in result["error"]["message"]
            assert calls.call_count == 0
            listed = await rpc(api, endpoint, credentials, "tools/list")
            assert listed["result"]["tools"] == []
            # Explicit new publication captures a new proof, old release/digest remain immutable.
            updated = await publish(
                admin, (await admin.api.get(ADMIN + "/" + expert["id"])).json(), "2.0.0"
            )
            assert (await resolution(api, updated, h))["can_prepare"]
        elif change == "description":
            assert result["error"]["data"]["code"] == "expert_behavior_changed"
            assert calls.call_count == 0
            strict = await resolution(api, expert, h, 3)
            assert not strict["can_prepare"]
            assert strict["dependencies"][0]["change_kind"] == "behavior"
        else:
            assert "result" in result and calls.call_count == 1
        async with env.sessions() as db:
            release = await db.get(ExpertRelease, UUID(expert["current_release"]["id"]))
            assert release.dependency_refs["connectors"][0]["tool_contracts"] == old
            assert release.sha256 == expert["current_release"]["sha256"]


async def test_required_unverified_blocks_v2_optional_can_skip_and_legacy_not_rewritten(
    env, upstream, monkeypatch
):
    admin, member, connector, expert, path = await setup(env, upstream)
    async with env.sessions() as db:
        release = await db.get(ExpertRelease, UUID(expert["current_release"]["id"]))
        # Fixture represents an original legacy release; production code never backfills hashes.
        refs = copy.deepcopy(release.dependency_refs)
        refs["connectors"][0].pop("tool_contracts")
        refs["connectors"][0].pop("capability_contracts")
        refs["connectors"][0].pop("reference_version")
        release.dependency_refs = refs
        await db.commit()
    async with native_client(env) as api:
        _, h = await native(env, monkeypatch, api, member)
        result = await resolution(api, expert, h)
        assert not result["can_prepare"] and result["dependencies"][0]["status"] == "unverified"
        assert result["dependencies"][0]["action"] == "contact_admin"
        summary = (await admin.api.get(ADMIN + "/" + expert["id"])).json()
        assert summary["dependency_issues"] == 1
        assert not (await resolution(api, expert, h, 3))["can_prepare"]
        assert (await resolution(api, expert, h, 1))["can_prepare"]
        optional = {
            "key": "lab",
            "label": "Optional",
            "required": False,
            "connector_id": connector["id"],
            "tools": ["add"],
        }
        second = await scope(
            admin, await publish(admin, await create(admin, content=content(connectors=[optional])))
        )
        assert (
            await admin.api.put(
                path + "/policy", json={"kind": "tools", "key": "add", "enabled": False}
            )
        ).status_code == 200
        result = await resolution(api, second, h)
        assert result["can_prepare"] and result["dependencies"][0]["status"] == "version_conflict"


@pytest.mark.parametrize("revocation", ["device", "expert", "connection", "replacement"])
async def test_late_revocation_before_dispatch_sends_no_tool_call(
    env, upstream, monkeypatch, revocation
):
    admin, member, connector, expert, _ = await setup(
        env, upstream, personal=revocation in {"connection", "replacement"}
    )
    async with native_client(env) as api:
        root, h = await native(env, monkeypatch, api, member)
        if revocation in {"connection", "replacement"}:
            catalog = await token(api, root, "mcp:catalog")
            connection_path = "/api/v1/desktop/mcp/connectors/" + connector["id"] + "/connection"
            assert (
                await api.put(
                    connection_path, headers=bearer(catalog), json={"values": {"token": "person-a"}}
                )
            ).status_code == 200
        endpoint = (await resolution(api, expert, h))["dependencies"][0]["mcp_endpoint"]
        credentials = await token(api, root, "mcp:" + connector["id"])
        original_discover = mcp.discover
        entered, proceed = asyncio.Event(), asyncio.Event()

        async def delayed(client):
            result = await original_discover(client)
            entered.set()
            await proceed.wait()
            return result

        calls = AsyncMock(wraps=mcp.call_tool)
        monkeypatch.setattr(mcp, "discover", delayed)
        monkeypatch.setattr(mcp, "call_tool", calls)
        waiting = asyncio.create_task(
            rpc(
                api,
                endpoint,
                credentials,
                "tools/call",
                {"name": "add", "arguments": {"a": 1, "b": 2}},
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        if revocation == "expert":
            response = await admin.api.post(
                ADMIN + "/" + expert["id"] + "/withdraw", json={"revision": expert["revision"]}
            )
            assert response.status_code == 200
        elif revocation in {"connection", "replacement"}:
            response = (
                await api.delete(connection_path, headers=bearer(catalog))
                if revocation == "connection"
                else await api.put(
                    connection_path, headers=bearer(catalog), json={"values": {"token": "person-b"}}
                )
            )
            assert response.status_code == 200, response.text
        else:
            assert (
                await api.post(
                    "/api/v1/desktop/logout", json={"refresh_token": root["refresh_token"]}
                )
            ).status_code == 200
        proceed.set()
        result = await asyncio.wait_for(waiting, 5)
        assert "error" in result and calls.call_count == 0


async def test_revocation_after_dispatch_withholds_result_without_repeating_call(
    env, upstream, monkeypatch
):
    admin, member, connector, expert, _ = await setup(env, upstream)
    async with native_client(env) as api:
        root, h = await native(env, monkeypatch, api, member)
        endpoint = (await resolution(api, expert, h))["dependencies"][0]["mcp_endpoint"]
        credentials = await token(api, root, "mcp:" + connector["id"])
        original_call = mcp.call_tool
        entered, proceed = asyncio.Event(), asyncio.Event()

        async def delayed(*args):
            result = await original_call(*args)
            entered.set()
            await proceed.wait()
            return result

        calls = AsyncMock(wraps=delayed)
        monkeypatch.setattr(mcp, "call_tool", calls)
        waiting = asyncio.create_task(
            rpc(
                api,
                endpoint,
                credentials,
                "tools/call",
                {"name": "add", "arguments": {"a": 1, "b": 2}},
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        assert (
            await admin.api.post(
                ADMIN + "/" + expert["id"] + "/withdraw", json={"revision": expert["revision"]}
            )
        ).status_code == 200
        proceed.set()
        result = await asyncio.wait_for(waiting, 5)
        assert "error" in result and "result" not in result and calls.call_count == 1


async def test_four_kind_proof_filters_list_and_blocks_changed_prompt(env, upstream, monkeypatch):
    admin, member, connector, expert, path = await setup(env, upstream, tools=None)
    async with native_client(env) as api:
        root, h = await native(env, monkeypatch, api, member)
        envelope = (await api.get(BASE + "/" + expert["id"], headers=h)).json()
        ref = envelope["dependency_refs"]["connectors"][0]
        assert envelope["contract_version"] == 3
        assert set(ref["capability_contracts"]) == {"tools", "prompts", "resources", "templates"}
        assert "greet" in ref["capability_contracts"]["prompts"]
        assert "fixture://guide" in ref["capability_contracts"]["resources"]
        assert "fixture://people/{name}" in ref["capability_contracts"]["templates"]
        strict = await resolution(api, expert, h, 3)
        assert strict["can_prepare"]
        endpoint = strict["dependencies"][0]["mcp_endpoint"]
        credentials = await token(api, root, "mcp:" + connector["id"])
        for method, field in [
            ("prompts/list", "prompts"),
            ("resources/list", "resources"),
            ("resources/templates/list", "resourceTemplates"),
        ]:
            listed = await rpc(api, endpoint, credentials, method)
            assert listed["result"][field]
        assert "result" in await rpc(
            api,
            endpoint,
            credentials,
            "prompts/get",
            {"name": "greet", "arguments": {"name": "Ada"}},
        )
        assert "result" in await rpc(
            api, endpoint, credentials, "resources/read", {"uri": "fixture://guide"}
        )
        assert "result" in await rpc(
            api, endpoint, credentials, "resources/read", {"uri": "fixture://people/Ada"}
        )
        original = mcp.discover

        async def changed(client):
            entries = copy.deepcopy(await original(client))
            for entry in entries:
                if entry["kind"] == "prompts" and entry["key"] == "greet":
                    entry["description"] = entry["definition"]["description"] = "changed behavior"
            return entries

        monkeypatch.setattr(mcp, "discover", changed)
        assert (await admin.api.post(path + "/discover")).status_code == 200
        strict = await resolution(api, expert, h, 3)
        assert strict["dependencies"][0]["status"] == "version_conflict"
        assert strict["dependencies"][0]["change_kind"] == "behavior"
        summary = (await admin.api.get(ADMIN + "/" + expert["id"])).json()
        assert summary["dependency_issues"] == 1 and summary["has_changes"]
        listed = await rpc(api, endpoint, credentials, "prompts/list")
        assert listed["result"]["prompts"] == []
        denied = await rpc(
            api,
            endpoint,
            credentials,
            "prompts/get",
            {"name": "greet", "arguments": {"name": "Ada"}},
        )
        assert denied["error"]["data"]["code"] == "expert_behavior_changed"


async def test_null_tool_draft_freezes_current_tools_on_publication(env, upstream, monkeypatch):
    admin, member, connector, _, _ = await setup(env, upstream)
    ref = {
        "key": "all",
        "label": "All",
        "required": True,
        "connector_id": connector["id"],
        "tools": None,
    }
    expert = await scope(
        admin, await publish(admin, await create(admin, content=content(connectors=[ref])))
    )
    async with native_client(env) as api:
        _, h = await native(env, monkeypatch, api, member)
        envelope = (await api.get(BASE + "/" + expert["id"], headers=h)).json()
        locked = envelope["dependency_refs"]["connectors"][0]
        assert locked["tools"] is not None and set(locked["tools"]) == set(
            locked["capability_contracts"]["tools"]
        )
        assert "add" in locked["tools"]


async def test_connector_revisions_separate_presentation_and_permission(env, upstream, monkeypatch):
    admin, member, connector, _, path = await setup(env, upstream)
    async with native_client(env) as api:
        root, _ = await native(env, monkeypatch, api, member)
        catalog = await token(api, root, "mcp:catalog")
        url = "/api/v1/desktop/mcp/connectors/" + connector["id"]
        first_response = await api.get(url, headers=bearer(catalog))
        assert first_response.status_code == 200
        first = first_response.json()
        assert {(c["kind"], c["key"]) for c in first["capability_revisions"]} >= {
            ("tools", "add"),
            ("prompts", "greet"),
            ("resources", "fixture://guide"),
            ("templates", "fixture://people/{name}"),
        }
        assert all(len(v) == 64 for v in first["revisions"].values())
        response = await admin.api.put(
            path + "/presentation",
            json={
                "version": connector["version"],
                "display_name": "New label",
                "description": connector["description"],
                "icon": connector["icon"],
                "examples": connector["examples"],
            },
        )
        assert response.status_code == 200, response.text
        second = (await api.get(url, headers=bearer(catalog))).json()
        assert second["revisions"]["display"] != first["revisions"]["display"]
        for field in ("connection", "authorization", "capabilities", "behavior"):
            assert second["revisions"][field] == first["revisions"][field]
        assert (
            await admin.api.put(
                path + "/policy", json={"kind": "prompts", "key": "greet", "enabled": False}
            )
        ).status_code == 200
        third = (await api.get(url, headers=bearer(catalog))).json()
        assert third["revisions"]["authorization"] != second["revisions"]["authorization"]
        assert third["revisions"]["connection"] == second["revisions"]["connection"]
        assert ("prompts", "greet") not in {
            (c["kind"], c["key"]) for c in third["capability_revisions"]
        }


@pytest.mark.parametrize(
    "kind,key,uri,list_method,field",
    [
        ("resources", "fixture://guide", "fixture://guide", "resources/list", "resources"),
        (
            "templates",
            "fixture://people/{name}",
            "fixture://people/Ada",
            "resources/templates/list",
            "resourceTemplates",
        ),
    ],
)
async def test_selected_resource_contract_change_blocks_read(
    env, upstream, monkeypatch, kind, key, uri, list_method, field
):
    admin, member, connector, expert, path = await setup(env, upstream)
    async with native_client(env) as api:
        root, h = await native(env, monkeypatch, api, member)
        strict = await resolution(api, expert, h, 3)
        assert strict["can_prepare"]
        endpoint = strict["dependencies"][0]["mcp_endpoint"]
        invocation = await token(api, root, "mcp:" + connector["id"])
        original = mcp.discover

        async def changed(client):
            entries = copy.deepcopy(await original(client))
            for item in entries:
                if item["kind"] == kind and item["key"] == key:
                    item["definition"]["mimeType"] = "application/json"
            return entries

        monkeypatch.setattr(mcp, "discover", changed)
        assert (await admin.api.post(path + "/discover")).status_code == 200
        assert (
            await admin.api.put(path + "/policy", json={"kind": kind, "key": key, "enabled": True})
        ).status_code == 200
        strict = await resolution(api, expert, h, 3)
        assert strict["dependencies"][0]["status"] == "version_conflict"
        assert strict["dependencies"][0]["change_kind"] == "contract"
        listed = await rpc(api, endpoint, invocation, list_method)
        assert all(
            item.get("uri") != key and item.get("uriTemplate") != key
            for item in listed["result"][field]
        )
        denied = await rpc(api, endpoint, invocation, "resources/read", {"uri": uri})
        assert denied["error"]["data"]["code"] == "expert_contract_changed"


async def test_new_unverified_release_blocks_prepare_and_gateway(env, monkeypatch, upstream):
    # No discovery is performed: the contract must stay unverified without external DNS.
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, member = await env.client(), await env.client(role="member")
    connector = await connector_create(admin, transport=transport, url=url)
    connector = await connector_update(admin, connector, enabled=True)
    ref = {
        "key": "unknown",
        "label": "Unknown",
        "required": True,
        "connector_id": connector["id"],
        "tools": None,
    }
    expert = await scope(
        admin, await publish(admin, await create(admin, content=content(connectors=[ref])))
    )
    async with native_client(env) as api:
        root, h = await native(env, monkeypatch, api, member)
        envelope = (await api.get(BASE + "/" + expert["id"], headers=h)).json()
        locked = envelope["dependency_refs"]["connectors"][0]
        assert envelope["contract_version"] == 3
        assert locked["reference_version"] == 3
        assert "capability_contracts" not in locked
        for version in (1, 3):
            resolved = await resolution(api, expert, h, version)
            assert not resolved["can_prepare"]
            assert resolved["dependencies"][0]["status"] == "unverified"
            assert resolved["dependencies"][0]["action"] == "contact_admin"
        invocation = await token(api, root, "mcp:" + connector["id"])
        endpoint = resolved["dependencies"][0]["mcp_endpoint"]
        assert (await rpc(api, endpoint, invocation, "tools/list"))["error"]["data"][
            "code"
        ] == "expert_unverified"
