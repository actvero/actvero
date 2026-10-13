"""Unified channel diagnostics: strict input, one admission, metadata-only recovery."""

import asyncio
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel
from test_llm_execution import configured as configure_chat
from test_llm_execution import upstream as chat_upstream
from test_mcp import listening

from app.modules.audit.models import AuditEvent
from app.modules.llm.diagnostic_schemas import ChatDiagnostic
from app.modules.llm.models import ModelCall, ModelChannel, RouteHealth
from app.modules.tenants.models import Tenant

pytestmark = pytest.mark.asyncio
env = identity_env


def chat_body(version: int, request_id: str, *, prompt: str = "private-prompt") -> dict:
    return {
        "version": version,
        "request_id": request_id,
        "upstream_id": "test-model",
        "operation": "chat",
        "endpoint": "chat_completions",
        "stream": False,
        "input": {"prompt": prompt, "max_output_tokens": 8},
    }


async def test_strict_diagnostic_contract():
    body = chat_body(1, str(uuid4()))
    assert ChatDiagnostic.model_validate(body).input.prompt == "private-prompt"
    for invalid in (
        {**body, "endpoint": "embeddings"},
        {**body, "stream": "invalid"},
        {**body, "input": {**body["input"], "unexpected": "x"}},
        {**body, "certify_health": True},
        {**body, "binding_id": str(uuid4())},
    ):
        with pytest.raises(ValueError):
            ChatDiagnostic.model_validate(invalid)


async def test_unified_one_send_receipt_and_filtered_metadata(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    upstream, calls = FastAPI(), []

    @upstream.post("/{path:path}")
    async def reply(path: str, request: Request):
        calls.append((path, await request.json()))
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "private-answer"},
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        row = await create_channel(
            admin,
            base_url=root + "/v1",
            api_key="fake-key",
            models=[{"id": "test-model"}],
            declared_apis=["chat_completions"],
        )
        request_id = str(uuid4())
        path = f"/api/v1/llm/channels/{row['id']}/diagnostics"
        body = chat_body(row["version"], request_id)
        result = await admin.api.post(path, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["ok"] is True
        assert result.json()["request_id"] == request_id
        assert len(calls) == 1
        assert calls[0][0] == "v1/chat/completions"

        # A lost response is queried under the original ID. Replays and changed
        # payloads cannot cause another supplier dispatch or recover old output.
        same = await admin.api.post(path, json=body)
        changed = await admin.api.post(
            path, json=chat_body(row["version"], request_id, prompt="changed")
        )
        assert same.status_code == changed.status_code == 409
        assert len(calls) == 1
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["channel_id"] == row["id"]
        assert detail.json()["record"]["status"] == "success"
        assert detail.json()["media_available"] is False
        assert "private-prompt" not in detail.text
        assert "private-answer" not in detail.text
        assert "request_digest" not in detail.text
        assert (await member.api.get(f"/api/v1/llm/diagnostics/{request_id}")).status_code == 403

        filtered = await admin.api.get(
            f"/api/v1/llm/channels/{row['id']}/tests",
            params={"operation": "chat", "status": "success", "channel_version": row["version"]},
        )
        assert filtered.status_code == 200, filtered.text
        assert [entry["request_id"] for entry in filtered.json()] == [request_id]
        mismatched = await admin.api.get(
            f"/api/v1/llm/channels/{row['id']}/tests",
            params={"status": "failure"},
        )
        assert mismatched.status_code == 200
        assert mismatched.json() == []

        invalid = await admin.api.post(
            path, json={**chat_body(row["version"], str(uuid4())), "stream": "invalid"}
        )
        assert invalid.status_code == 422
        assert len(calls) == 1


async def test_concurrent_same_request_id_never_sends_twice(env):
    admin = await env.client()
    upstream, calls = FastAPI(), []

    @upstream.post("/{path:path}")
    async def reply(path: str, request: Request):
        calls.append(path)
        await asyncio.sleep(0.05)
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"},
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
        }

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        row = await create_channel(
            admin,
            base_url=root + "/v1",
            api_key="fake-key",
            models=[{"id": "test-model"}],
        )
        path = f"/api/v1/llm/channels/{row['id']}/diagnostics"
        body = chat_body(row["version"], str(uuid4()))
        first, second = await asyncio.gather(
            admin.api.post(path, json=body), admin.api.post(path, json=body)
        )
        assert sorted((first.status_code, second.status_code)) == [200, 409]
        assert len(calls) == 1


async def test_explicit_binding_recovery_certifies_without_enabling_channel(env):
    admin = await env.client()
    upstream, state = chat_upstream()
    async with listening(upstream) as root:
        model, channels = await configure_chat(env, admin, root)
        selected = channels[0]
        env.provider.settings.llm_allowed_private_origins = [root]
        async with env.sessions() as db:
            row = await db.get(ModelChannel, UUID(selected["id"]))
            row.manual_enabled = False
            await db.commit()
        request_id = str(uuid4())
        body = {
            **chat_body(selected["version"], request_id, prompt="fixture"),
            "upstream_id": "vendor-chat",
            "input": {"prompt": "fixture", "max_output_tokens": 50},
            "certify_health": True,
            "model_id": model["id"],
            "model_version": model["version"],
            "binding_id": model["bindings"][0]["binding_id"],
        }
        response = await admin.api.post(
            f"/api/v1/llm/channels/{selected['id']}/diagnostics", json=body
        )
        assert response.status_code == 200, response.text
        assert response.json()["ok"] is True
        assert response.json()["health_certification"] == "certified"
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request_id}")
        assert detail.json()["record"]["health_certification"] == "certified"
        async with env.sessions() as db:
            channel = await db.get(ModelChannel, UUID(selected["id"]))
            assert channel.manual_enabled is False
            health = list(await db.scalars(select(RouteHealth)))
            assert any(item.tested_at is not None and item.probe_until is None for item in health)
        assert len(state["calls"]) == 1


async def test_cancelled_recovery_keeps_unknown_receipt_and_releases_lease(env):
    admin = await env.client()
    upstream, state = chat_upstream()
    state["entered"] = asyncio.Event()
    state["release"] = asyncio.Event()
    async with listening(upstream) as root:
        model, channels = await configure_chat(env, admin, root)
        selected = channels[0]
        env.provider.settings.llm_allowed_private_origins = [root]
        request_id = str(uuid4())
        body = {
            **chat_body(selected["version"], request_id, prompt="fixture"),
            "upstream_id": "vendor-chat",
            "input": {"prompt": "fixture", "max_output_tokens": 50},
            "certify_health": True,
            "model_id": model["id"],
            "model_version": model["version"],
            "binding_id": model["bindings"][0]["binding_id"],
        }
        path = f"/api/v1/llm/channels/{selected['id']}/diagnostics"
        task = asyncio.create_task(admin.api.post(path, json=body))
        await asyncio.wait_for(state["entered"].wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state["release"].set()
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request_id}")
        assert detail.status_code == 200, detail.text
        record = detail.json()["record"]
        assert record["status"] == "unconfirmed"
        assert record["attempt"]["sent"] is True
        assert record["health_certification"] == "not_certified"
        unconfirmed = await admin.api.get(
            f"/api/v1/llm/channels/{selected['id']}/tests",
            params={"status": "unconfirmed"},
        )
        assert [entry["request_id"] for entry in unconfirmed.json()] == [request_id]
        async with env.sessions() as db:
            health = list(await db.scalars(select(RouteHealth)))
            assert health and all(item.probe_until is None for item in health)
        duplicate = await admin.api.post(path, json=body)
        assert duplicate.status_code == 409
        assert len(state["calls"]) == 1


async def test_cancelled_sent_evidence_survives_tenant_lock_longer_than_cleanup_limit(env):
    admin = await env.client()
    upstream, state = chat_upstream()
    state["entered"] = asyncio.Event()
    state["release"] = asyncio.Event()
    async with listening(upstream) as root:
        model, channels = await configure_chat(env, admin, root)
        selected = channels[0]
        env.provider.settings.llm_allowed_private_origins = [root]
        request_id = str(uuid4())
        body = {
            **chat_body(selected["version"], request_id, prompt="fixture"),
            "upstream_id": "vendor-chat",
            "input": {"prompt": "fixture", "max_output_tokens": 50},
            "certify_health": True,
            "model_id": model["id"],
            "model_version": model["version"],
            "binding_id": model["bindings"][0]["binding_id"],
        }
        path = f"/api/v1/llm/channels/{selected['id']}/diagnostics"
        task = asyncio.create_task(admin.api.post(path, json=body))
        await asyncio.wait_for(state["entered"].wait(), 5)

        locked = asyncio.Event()

        async def hold_tenant_lock() -> None:
            async with env.sessions() as db:
                await db.scalar(
                    select(Tenant.id).where(Tenant.id == admin.tenant.id).with_for_update()
                )
                locked.set()
                await asyncio.sleep(4.2)
                await db.commit()

        holder = asyncio.create_task(hold_tenant_lock())
        await asyncio.wait_for(locked.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        state["release"].set()
        assert not holder.done()  # Query while the certification lock is still held.
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request_id}")
        assert detail.status_code == 200, detail.text
        record = detail.json()["record"]
        assert record["status"] == "unconfirmed"
        assert record["health_certification"] == "not_certified"
        assert record["attempt"]["sent"] is True
        assert record["attempt"]["error_code"] == "caller_cancelled"
        assert record["attempt"]["health_cleanup"] == "lease_expiry_pending"
        await holder
        async with env.sessions() as db:
            health = list(await db.scalars(select(RouteHealth)))
            assert health and all(item.tested_at is None for item in health)
        duplicate = await admin.api.post(path, json=body)
        assert duplicate.status_code == 409
        assert len(state["calls"]) == 1


async def test_post_result_cancel_does_not_overwrite_committed_success(env):
    admin = await env.client()
    upstream, state = chat_upstream()
    state["entered"] = asyncio.Event()
    state["release"] = asyncio.Event()
    async with listening(upstream) as root:
        model, channels = await configure_chat(env, admin, root)
        selected = channels[0]
        env.provider.settings.llm_allowed_private_origins = [root]
        request_id = str(uuid4())
        body = {
            **chat_body(selected["version"], request_id, prompt="fixture"),
            "upstream_id": "vendor-chat",
            "input": {"prompt": "fixture", "max_output_tokens": 50},
            "certify_health": True,
            "model_id": model["id"],
            "model_version": model["version"],
            "binding_id": model["bindings"][0]["binding_id"],
        }
        path = f"/api/v1/llm/channels/{selected['id']}/diagnostics"
        task = asyncio.create_task(admin.api.post(path, json=body))
        await asyncio.wait_for(state["entered"].wait(), 5)
        locked = asyncio.Event()

        async def hold_tenant_lock() -> None:
            async with env.sessions() as db:
                await db.scalar(
                    select(Tenant.id).where(Tenant.id == admin.tenant.id).with_for_update()
                )
                locked.set()
                await asyncio.sleep(4.2)
                await db.commit()

        holder = asyncio.create_task(hold_tenant_lock())
        await asyncio.wait_for(locked.wait(), 3)
        state["release"].set()  # Complete SDK output; only health certification is blocked.
        for _ in range(80):
            async with env.sessions() as db:
                call = await db.get(ModelCall, UUID(request_id))
                if call is not None and call.status == "succeeded":
                    break
            await asyncio.sleep(0.025)
        else:
            pytest.fail("execution evidence did not commit before health cleanup")
        assert not holder.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request_id}")
        assert detail.status_code == 200, detail.text
        record = detail.json()["record"]
        assert record["status"] == "success"
        assert record["attempt"]["sent"] is True
        assert record["attempt"]["error_code"] is None
        assert record["health_certification"] == "not_certified"
        assert record["attempt"]["health_cleanup"] == "lease_expiry_pending"
        await holder
        async with env.sessions() as db:
            health = list(await db.scalars(select(RouteHealth)))
            assert health and all(item.tested_at is None for item in health)
        assert len(state["calls"]) == 1


async def test_legacy_audit_detail_and_filtered_history_have_no_invented_attempt(env):
    admin = await env.client()
    row = await create_channel(admin)
    request_id = str(uuid4())
    basic = {
        "request_id": request_id,
        "model": "legacy-model",
        "operation": "embedding",
        "channel_version": str(row["version"]),
    }
    async with env.sessions() as db:
        db.add_all(
            [
                AuditEvent(
                    tenant_id=admin.tenant.id,
                    actor_id=admin.user.id,
                    actor_name="test-admin",
                    action="llm.channel.test.start",
                    target_id=UUID(row["id"]),
                    target_name="legacy",
                    details=basic,
                ),
                AuditEvent(
                    tenant_id=admin.tenant.id,
                    actor_id=admin.user.id,
                    actor_name="test-admin",
                    action="llm.channel.test.finish",
                    target_id=UUID(row["id"]),
                    target_name="legacy",
                    result="success",
                    details={**basic, "duration_ms": "42"},
                ),
            ]
        )
        await db.commit()
    detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request_id}")
    assert detail.status_code == 200, detail.text
    record = detail.json()["record"]
    assert record["record_version"] == "legacy_audit"
    assert record["status"] == "success"
    assert record["attempt"] is None
    assert detail.json()["media_available"] is False
    filtered = await admin.api.get(
        f"/api/v1/llm/channels/{row['id']}/tests",
        params={"operation": "embedding", "status": "success", "channel_version": row["version"]},
    )
    assert [entry["request_id"] for entry in filtered.json()] == [request_id]
