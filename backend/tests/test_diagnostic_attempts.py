"""Durable diagnostic evidence across post-dispatch configuration and access races."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from test_channel_testing import create, probe
from test_identity_access import env as identity_env
from test_mcp import listening

from app.modules.audit.models import AuditEvent
from app.modules.llm.models import CatalogModel, ModelCall, RouteHealth, UsageSettlement
from app.modules.members.models import Membership

env = identity_env
pytestmark = pytest.mark.asyncio


def slow_embedding():
    upstream = FastAPI()
    started, release = asyncio.Event(), asyncio.Event()
    calls: list[str] = []

    @upstream.post("/{path:path}")
    async def reply(path: str):
        calls.append(path)
        started.set()
        await release.wait()
        return {
            "data": [{"index": 0, "embedding": [0.1] * 12}],
            "usage": {"prompt_tokens": 7, "total_tokens": 7},
        }

    return upstream, calls, started, release


async def persisted(env, request_id: str) -> ModelCall:
    async with env.sessions() as db:
        call = await db.get(ModelCall, UUID(request_id))
        assert call is not None
        assert call.source == "channel_diagnostic" and call.model_id is None
        assert len(call.attempts) == 1
        assert await db.scalar(select(func.count()).select_from(CatalogModel)) == 0
        assert await db.scalar(select(func.count()).select_from(RouteHealth)) == 0
        assert await db.scalar(select(func.count()).select_from(UsageSettlement)) == 0
        serialized = json.dumps({"attempts": call.attempts, "usage": call.usage})
        assert not any(
            secret in serialized for secret in ("private text", "private-key", "private query")
        )
        return call


async def test_channel_version_change_returns_409_after_persisting_attempt(env):
    admin = await env.client()
    upstream, calls, started, release = slow_embedding()
    async with listening(upstream) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        pending = asyncio.create_task(admin.api.post(path + "/test", json=probe("embedding")))
        await asyncio.wait_for(started.wait(), 10)
        changed = await admin.api.put(
            path + "/status", json={"version": 1, "manual_enabled": False}
        )
        assert changed.status_code == 200, changed.text
        release.set()
        response = await pending
    assert response.status_code == 409 and len(calls) == 1
    assert not any(secret in response.text for secret in ("private text", "private-key"))
    history = (await admin.api.get(path + "/tests")).json()
    assert len(history) == 1
    record = history[0]
    assert record["record_version"] == "attempt_v1" and record["stale"]
    assert record["status"] == "success"
    assert record["attempt"]["sent"] is True and record["attempt"]["upstream_terminal"] is True
    call = await persisted(env, record["request_id"])
    assert call.status == "succeeded" and call.attempts[0] == record["attempt"]


async def test_member_revocation_returns_403_but_keeps_private_evidence(env):
    admin = await env.client()
    observer = await env.client(tenant=admin.tenant)
    upstream, calls, started, release = slow_embedding()
    async with listening(upstream) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        pending = asyncio.create_task(admin.api.post(path + "/test", json=probe("embedding")))
        await asyncio.wait_for(started.wait(), 10)
        async with env.sessions() as db:
            member = await db.get(Membership, admin.member.id)
            assert member is not None
            member.status = "removed"
            member.version += 1
            await db.commit()
        release.set()
        response = await pending
    assert response.status_code == 403 and len(calls) == 1
    assert not any(secret in response.text for secret in ("private text", "private-key"))
    assert (await admin.api.get(path + "/tests")).status_code == 403
    history = (await observer.api.get(path + "/tests")).json()
    assert len(history) == 1
    record = history[0]
    assert record["record_version"] == "attempt_v1"
    assert record["status"] == "success" and record["attempt"]["sent"] is True
    call = await persisted(env, record["request_id"])
    assert call.actor_id == admin.user.id and call.attempts[0] == record["attempt"]
    # The list/detail projection must not fall back to an unfinished audit event.
    summary = (await observer.api.get(path)).json()["last_diagnostic"]
    assert summary["status"] == "success" and summary["ok"] is True
    assert summary["request_id"] == record["request_id"]
    assert summary["duration_ms"] == record["duration_ms"]


async def test_audit_only_history_is_labelled_legacy_without_attempt(env):
    admin = await env.client()
    upstream = FastAPI()
    async with listening(upstream) as url:
        path = await create(admin, url)
    request_id = str(uuid4())
    channel_id = UUID(path.rsplit("/", 1)[-1])
    async with env.sessions() as db:
        db.add(
            AuditEvent(
                tenant_id=admin.tenant.id,
                actor_id=admin.user.id,
                actor_name="Administrator",
                action="llm.channel.test.start",
                target_id=channel_id,
                target_name="Probe",
                details={
                    "request_id": request_id,
                    "model": "opaque-model",
                    "operation": "embedding",
                    "channel_version": "1",
                },
            )
        )
        db.add(
            AuditEvent(
                tenant_id=admin.tenant.id,
                actor_id=admin.user.id,
                actor_name="Administrator",
                action="llm.channel.test.finish",
                target_id=channel_id,
                target_name="Probe",
                result="success",
                details={"request_id": request_id, "duration_ms": "20"},
            )
        )
        await db.commit()
    history = (await admin.api.get(path + "/tests")).json()
    assert len(history) == 1
    assert history[0]["record_version"] == "legacy_audit"
    assert history[0]["attempt"] is None and history[0]["status"] == "success"
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(ModelCall)) == 0
