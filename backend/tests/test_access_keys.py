"""Real database, real loopback model/MCP transports; identity is a test double."""

import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx2
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from llm_billing_helpers import billing
from sqlalchemy import select
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model
from test_llm_execution import configured, payload
from test_llm_execution import upstream as chat_upstream
from test_llm_retrieval import configured as retrieval_model
from test_llm_retrieval import upstream as retrieval_upstream
from test_llm_routing import update as update_model
from test_mcp import create as create_mcp
from test_mcp import listening
from test_mcp import update as update_mcp
from test_mcp import upstream as mcp_fixture

from app.modules.access_keys.models import AccessKey
from app.modules.auth.service import now
from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.models import ModelCall, UsageSettlement
from app.modules.members.models import Membership

env = identity_env
upstream = mcp_fixture
pytestmark = pytest.mark.asyncio
OWN = "/api/v1/account/access-keys"
ADMIN = "/api/v1/access-keys"
LLM = "/api/llm/v1"


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


def grant(row, kind="llm", actions=None):
    return {"kind": kind, "resource_id": row["id"], "actions": actions or ["read", "invoke"]}


async def create(actor, grants=None, **extra):
    body = {
        "creation_id": str(uuid4()),
        "name": "Local Agent",
        **(
            {"expires_at": (now() + timedelta(days=7)).isoformat(), "grants": grants}
            if grants is not None
            else {}
        ),
        **extra,
    }
    result = await actor.api.post(OWN, json=body)
    assert result.status_code == 200, result.text
    return result.json(), body


def headers(key):
    return {"Authorization": "Bearer " + key["secret"]}


async def test_self_service_metadata_csrf_scope_and_admin_governance(env):
    admin, member, other = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    row = await create_mcp(admin)
    row = await update_mcp(admin, row, enabled=True)
    key, body = await create(member, [grant(row, "mcp")])
    assert key["key"]["scope_mode"] == "selected"
    assert (await member.api.post(OWN, json=body)).status_code == 409
    assert (
        await member.api.post(OWN, json=body, headers={"x-csrf-token": "wrong"})
    ).status_code == 403
    for url in (OWN, ADMIN):
        result = await admin.api.get(url)
        assert key["secret"] not in result.text and "token_hash" not in result.text
    assert (await member.api.get(ADMIN)).status_code == 403
    assert (await other.api.get(OWN)).json()["total"] == 0
    target = "/" + key["key"]["id"]
    action = {"version": 1, "action": "disable"}
    assert (await other.api.patch(OWN + target, json=action)).status_code == 404
    assert (await other.api.get(OWN + target + "/usage")).status_code == 404
    async with env.sessions() as db:
        stored = await db.get(AccessKey, UUID(key["key"]["id"]))
        assert stored.token_hash != key["secret"] and key["secret"] not in str(stored.__dict__)
    assert (await admin.api.patch(ADMIN + target, json=action)).status_code == 200
    assert (
        await member.api.patch(OWN + target, json={"version": 2, "action": "enable"})
    ).status_code == 403
    enabled = await admin.api.patch(ADMIN + target, json={"version": 2, "action": "enable"})
    assert enabled.status_code == 200
    assert (
        await member.api.patch(OWN + target, json={"version": 2, "action": "revoke"})
    ).status_code == 409
    assert (
        await member.api.patch(OWN + target, json={"version": 3, "action": "revoke"})
    ).status_code == 200
    assert (
        await admin.api.patch(ADMIN + target, json={"version": 4, "action": "enable"})
    ).status_code == 409
    restricted = await create_mcp(
        admin, name="Private", audience="selected", member_ids=[str(other.member.id)]
    )
    restricted = await update_mcp(admin, restricted, enabled=True)
    assert (
        await member.api.post(
            OWN, json={**body, "creation_id": str(uuid4()), "grants": [grant(restricted, "mcp")]}
        )
    ).status_code == 403
    unknown = {
        **body,
        "creation_id": str(uuid4()),
        "grants": [{"kind": "skills", "resource_id": str(uuid4()), "actions": ["read"]}],
    }
    assert (await member.api.post(OWN, json=unknown)).status_code == 422


async def test_expiry_org_policy_member_revocation_and_auth_separation(env):
    admin, member = await env.client(), await env.client(role="member")
    svc = await create_mcp(admin)
    svc = await update_mcp(admin, svc, enabled=True)
    key, body = await create(member, [grant(svc, "mcp")])
    async with native_client(env) as api:
        catalog = "/api/v1/gateway/mcp/services"
        assert (await api.get(catalog, headers=headers(key))).status_code == 200
        for url in (OWN, ADMIN, "/api/v1/desktop/me", "/api/v1/llm/models", "/api/v1/mcp/services"):
            assert (await api.get(url, headers=headers(key))).status_code == 401
        assert (
            await api.get(catalog, headers={**headers(key), "origin": "https://evil.test"})
        ).status_code == 401
        assert (await member.api.get(catalog, headers=headers(key))).status_code == 401
        policy = {"version": 0, "enabled": True, "max_days": 1}
        assert (await member.api.put(ADMIN + "/policy", json=policy)).status_code == 403
        assert (await admin.api.put(ADMIN + "/policy", json=policy)).status_code == 200
        assert (await api.get(catalog, headers=headers(key))).status_code == 401
        assert (
            await member.api.post(OWN, json={**body, "creation_id": str(uuid4())})
        ).status_code == 422
        assert (
            await admin.api.put(ADMIN + "/policy", json={**policy, "version": 1, "max_days": None})
        ).status_code == 200
        assert (await api.get(catalog, headers=headers(key))).status_code == 200
        async with env.sessions() as db:
            person = await db.get(Membership, member.member.id)
            person.revoked_at = now()
            await db.commit()
        # Restore/active membership does not resurrect keys issued before suspension.
        assert (await api.get(catalog, headers=headers(key))).status_code == 403
        async with env.sessions() as db:
            person = await db.get(Membership, member.member.id)
            person.revoked_at = None
            row = await db.get(AccessKey, UUID(key["key"]["id"]))
            row.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (await api.get(catalog, headers=headers(key))).status_code == 401


async def test_name_only_key_follows_live_permissions_without_admin_bypass(env):
    admin, member = await env.client(), await env.client(role="member")
    key, body = await create(member)
    assert key["key"]["scope_mode"] == "member"
    assert key["key"]["grants"] == [] and key["key"]["expires_at"] is None
    assert (await member.api.post(OWN, json={**body, "name": "  "})).status_code == 422
    assert (
        await member.api.post(OWN, json={**body, "creation_id": str(uuid4()), "grants": []})
    ).status_code == 422
    catalog = "/api/v1/gateway/mcp/services"
    async with native_client(env) as api:
        assert (await api.get(catalog, headers=headers(key))).json()["items"] == []
        # A resource granted after key creation becomes usable without regenerating the key.
        svc = await create_mcp(admin, audience="selected", member_ids=[str(member.member.id)])
        svc = await update_mcp(admin, svc, enabled=True)
        assert [
            r["id"] for r in (await api.get(catalog, headers=headers(key))).json()["items"]
        ] == [svc["id"]]
        admin_key, _ = await create(admin)
        assert (await api.get(catalog, headers=headers(admin_key))).json()["items"] == []
        endpoint = "/api/mcp/services/" + svc["id"]
        assert (
            await api.post(endpoint, headers=headers(admin_key), json={"method": "tools/list"})
        ).status_code == 404
        svc = await update_mcp(admin, svc, audience="selected", member_ids=[])
        assert (await api.get(catalog, headers=headers(key))).json()["items"] == []
        assert (
            await api.post(endpoint, headers=headers(key), json={"method": "tools/list"})
        ).status_code == 404
        # Inherited credentials remain unusable for administration and desktop sessions.
        for url in (OWN, ADMIN, "/api/v1/desktop/me", "/api/v1/llm/models"):
            assert (await api.get(url, headers=headers(admin_key))).status_code == 401


async def test_name_only_key_expiry_uses_current_organization_policy(env):
    admin, member = await env.client(), await env.client(role="member")
    permanent, _ = await create(member)
    policy = {"version": 0, "enabled": True, "max_days": 3}
    assert (await admin.api.put(ADMIN + "/policy", json=policy)).status_code == 200
    limited, _ = await create(member)
    async with env.sessions() as db:
        row = await db.get(AccessKey, UUID(limited["key"]["id"]))
        assert row.expires_at - row.created_at == timedelta(days=3)
    async with native_client(env) as api:
        url = "/api/v1/gateway/mcp/services"
        assert (await api.get(url, headers=headers(limited))).status_code == 200
        assert (await api.get(url, headers=headers(permanent))).status_code == 401
        assert (
            await admin.api.put(ADMIN + "/policy", json={**policy, "version": 1, "enabled": False})
        ).status_code == 200
        assert (await api.get(url, headers=headers(limited))).status_code == 401
        assert (
            await member.api.post(OWN, json={"creation_id": str(uuid4()), "name": "blocked"})
        ).status_code == 403


@pytest.mark.parametrize("inherit", [False, True])
async def test_multi_model_key_chat_streaming_shared_quota_and_live_permissions(env, inherit):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    upstream, observed = chat_upstream()
    async with listening(upstream) as base:
        first, _ = await configured(env, admin, base)
        second = await create_model(
            admin,
            **{
                **{
                    k: v
                    for k, v in first.items()
                    if k
                    in {
                        "context_window",
                        "max_output",
                        "budget_price",
                        "bindings",
                        "access",
                        "capabilities",
                        "reasoning_options",
                    }
                },
                "name": "Other model",
                "bindings": [
                    {k: v for k, v in binding.items() if k != "binding_id"}
                    for binding in first["bindings"]
                ],
                "slug": "other-chat",
            },
        )
        key, _ = await create(member, None if inherit else [grant(first), grant(second)])
        other_key, _ = await create(member, [grant(first)])
        async with native_client(env) as api:
            catalog = await api.get(LLM + "/models", headers=headers(key))
            assert {m["id"] for m in catalog.json()["data"]} == {first["slug"], second["slug"]}
            assert "procurement" not in catalog.text and "USD" not in catalog.text
            for row in (first, second):
                response = await api.post(
                    LLM + "/chat/completions", json=payload(row), headers=headers(key)
                )
                assert response.status_code == 200, response.text
            stream = await api.post(
                LLM + "/chat/completions",
                json=payload(first, stream=True),
                headers=headers(other_key),
            )
            assert stream.status_code == 200 and "[DONE]" in stream.text
            async with env.sessions() as db:
                settlements = (await db.scalars(select(UsageSettlement))).all()
                assert len(settlements) == 3 and {r.member_id for r in settlements} == {
                    member.member.id
                }
                calls = (await db.scalars(select(ModelCall))).all()
                assert all(r.source == "access_key" and r.access_key_id for r in calls)
            usage = await member.api.get(OWN + "/" + key["key"]["id"] + "/usage")
            assert usage.status_code == 200 and usage.json()["total"] == 2
            assert not any(
                secret in usage.text
                for secret in ("prices", "private prompt", "USD", key["secret"])
            )
            assert (
                await api.post(
                    LLM + "/chat/completions", json=payload(second), headers=headers(other_key)
                )
            ).status_code == 403
            second = await update_model(
                admin, second, access={**second["access"], "enabled": False}
            )
            assert (
                await api.post(
                    LLM + "/chat/completions", json=payload(second), headers=headers(key)
                )
            ).status_code == 404
            assert len((await api.get(LLM + "/models", headers=headers(key))).json()["data"]) == 1
            # Quota follows the member, not key or credential replacement.
            async with env.sessions() as db:
                from app.modules.quota.models import QuotaPolicy

                rule = await db.scalar(select(QuotaPolicy))
                rule.rules = [{"kind": "fixed_hours", "hours": 5, "points": "0.001"}]
                await db.commit()
            before = len(observed["calls"])
            assert (
                await api.post(
                    LLM + "/chat/completions", json=payload(first), headers=headers(other_key)
                )
            ).status_code == 429
            assert len(observed["calls"]) == before


async def test_key_revoked_during_model_call_blocks_delivery_but_settles(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    upstream, observed = chat_upstream()
    async with listening(upstream) as base:
        model, _ = await configured(env, admin, base)
        key, _ = await create(member, [grant(model)])
        observed["entered"], observed["release"] = asyncio.Event(), asyncio.Event()
        async with native_client(env) as api:
            task = asyncio.create_task(
                api.post(LLM + "/chat/completions", json=payload(model), headers=headers(key))
            )
            await asyncio.wait_for(observed["entered"].wait(), 10)
            revoke = await admin.api.patch(
                ADMIN + "/" + key["key"]["id"], json={"version": 1, "action": "revoke"}
            )
            assert revoke.status_code == 200
            observed["release"].set()
            assert (await task).status_code == 401
            async with env.sessions() as db:
                charge = await db.scalar(select(UsageSettlement))
                assert charge.status == "settled" and charge.amount > 0


async def test_embedding_key_does_not_leak_upstream_auth_and_locks_space(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    upstream, requests = retrieval_upstream()
    async with listening(upstream) as base:
        model, _ = await retrieval_model(env, admin, base, enabled=True)
        key, _ = await create(member, [grant(model)])
        async with native_client(env) as api:
            result = await api.post(
                LLM + "/embeddings",
                json={"model": model["slug"], "input": ["hello"]},
                headers=headers(key),
            )
            assert result.status_code == 200, result.text
            assert all(key["secret"] not in str(r) for r in requests)
        result = await admin.api.put(
            "/api/v1/llm/models/" + model["id"], json={**model, "slug": "changed-space"}
        )
        assert result.status_code in (409, 422)


@pytest.mark.parametrize("inherit", [False, True])
async def test_mcp_sdk_key_scope_live_authorization_and_attribution(env, upstream, inherit):
    base, transport, url = upstream
    env.provider.settings.mcp_allowed_private_origins = [base]
    admin, member = await env.client(), await env.client(role="member")
    svc = await create_mcp(admin, transport=transport, url=url)
    path = "/api/v1/mcp/services/" + svc["id"]
    assert (await admin.api.post(path + "/discover")).status_code == 200
    svc = await update_mcp(admin, svc, enabled=True)
    key, _ = await create(member, None if inherit else [grant(svc, "mcp")])
    reader, _ = await create(member, [grant(svc, "mcp", ["read"])])

    def factory(**kwargs):
        return httpx2.AsyncClient(transport=httpx2.ASGITransport(app=env.app), **kwargs)

    endpoint = env.provider.settings.app_url + "/api/mcp/services/" + svc["id"]
    for token, allowed in ((key, True), (reader, False)):
        async with Client(
            StreamableHttpTransport(endpoint, headers=headers(token), httpx_client_factory=factory),
            mode="legacy",
            timeout=10,
            cache=False,
        ) as client:
            assert "add" in [t.name for t in await client.list_tools()]
            if allowed:
                assert "5" in str(await client.call_tool("add", {"a": 2, "b": 3}))
            else:
                with pytest.raises(
                    Exception, match="Server returned an error response|403|Forbidden"
                ):
                    await client.call_tool("add", {"a": 2, "b": 3})
            await admin.api.put(
                path + "/policy", json={"kind": "tools", "key": "add", "enabled": False}
            )
            assert "add" not in [t.name for t in await client.list_tools()]
            await admin.api.put(
                path + "/policy", json={"kind": "tools", "key": "add", "enabled": True}
            )
    history = (await member.api.get(OWN + "/" + key["key"]["id"] + "/usage")).json()
    assert any(r["kind"] == "mcp" and r["operation"] == "tools" for r in history["items"])
    await update_mcp(admin, svc, enabled=False)
    async with native_client(env) as api:
        assert (await api.get("/api/v1/gateway/mcp/services", headers=headers(key))).json()[
            "items"
        ] == []
        result = await api.post(
            endpoint,
            headers={**headers(key), "Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert result.status_code == 404
