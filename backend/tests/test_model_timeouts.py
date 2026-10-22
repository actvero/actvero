"""Real SDK streams keep progressing beyond the first-response and channel limits."""

import asyncio
import importlib.util
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import httpx
import httpx2
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from llm_billing_helpers import billing
from sqlalchemy import select
from test_desktop import bearer, native_client
from test_identity_access import env as identity_env
from test_llm_execution import BASE, GATEWAY, METER, configured, credentials, entries, payload
from test_llm_routing import update
from test_mcp import listening

from app.modules.auth.service import digest, now
from app.modules.desktop.models import DeviceSession
from app.modules.desktop_mcp.models import ResourceToken
from app.modules.llm.catalog_schemas import RoutingPolicy
from app.modules.llm.models import ModelChannel
from app.modules.llm.providers.timeouts import ExecutionTimeout, Timeouts

env = identity_env


@pytest.mark.asyncio
@pytest.mark.parametrize("revoke", [False, True])
async def test_resource_token_expiry_only_limits_admission_but_revocation_stops_stream(
    env, monkeypatch, revoke
):
    from test_llm_execution import upstream

    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    state["after_first"], state["continue_stream"] = asyncio.Event(), asyncio.Event()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            pending = asyncio.create_task(
                api.post(GATEWAY, headers=bearer(token), json=payload(model, stream=True))
            )
            await asyncio.wait_for(state["after_first"].wait(), 10)
            try:
                async with env.sessions() as db:
                    resource = await db.get(ResourceToken, digest(token["access_token"]))
                    resource.expires_at = now() - timedelta(seconds=1)
                    if revoke:
                        device = await db.get(DeviceSession, resource.device_id)
                        device.revoked_at = now()
                    await db.commit()
                await asyncio.sleep(1.5)  # The background access watch checks once a second.
            finally:
                state["continue_stream"].set()
            result = await asyncio.wait_for(pending, 10)
            if revoke:
                assert "device_revoked" in result.text and "[DONE]" not in result.text
            else:
                assert result.status_code == 200 and "[DONE]" in result.text, result.text
                assert '"error"' not in result.text
                assert (await entries(admin))[0]["status"] == "settled"
            rejected = await api.post(GATEWAY, headers=bearer(token), json=payload(model))
            assert rejected.status_code == 401
            assert rejected.json()["error"]["code"] == "resource_token_expired"
            assert len(state["calls"]) == 1


@pytest.mark.asyncio
async def test_transport_enforces_configured_connect_timeout_over_sdk_defaults(monkeypatch):
    from app.core.config import Settings
    from app.modules.llm.providers.sdk_transport import RuntimeTransport

    timeout = httpx.Timeout(120, connect=7, pool=7)
    transport = RuntimeTransport(
        "https://example.com", None, Settings(_env_file=None), "openai", timeout=timeout
    )
    observed = {}

    async def connect(request):
        observed.update(request.extensions["timeout"])
        raise httpx2.ConnectTimeout("synthetic connection stall")

    monkeypatch.setattr(transport.inner, "handle_async_request", connect)
    try:
        with pytest.raises(httpx2.ConnectTimeout):
            await transport.handle_async_request(
                httpx.Request(
                    "POST",
                    "https://example.com/chat/completions",
                    content=b"{}",
                    extensions={"timeout": httpx.Timeout(0.01).as_dict()},
                )
            )
        assert observed == timeout.as_dict()
        assert transport.failure.code == "upstream_connect_timeout"
    finally:
        await transport.aclose()


def provider(*, first_delay=0, chunk_delay=0, count=1):
    app, calls = FastAPI(), []

    @app.post("/{channel}/chat/completions")
    async def complete(channel: str, request: Request):
        body = await request.json()
        calls.append(body)

        async def events():
            await asyncio.sleep(first_delay)
            for i in range(count):
                if i:
                    await asyncio.sleep(chunk_delay)
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "id": "test",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": "vendor-chat",
                            "choices": [
                                {"index": 0, "delta": {"content": "part"}, "finish_reason": None}
                            ],
                        }
                    )
                    + "\n\n"
                )
            yield (
                "data: "
                + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
                + "\n\n"
            )
            yield ("data: " + json.dumps({"choices": [], "usage": METER}) + "\n\n")
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    return app, calls


@pytest.mark.asyncio
@pytest.mark.parametrize(("count", "delay", "minimum_ms"), [(7, 0.8, 4500), (45, 1.5, 65000)])
async def test_live_stream_outlasts_first_response_and_channel_timeout(
    env, monkeypatch, count, delay, minimum_ms
):
    admin = await env.client()
    await billing(admin)
    app, calls = provider(chunk_delay=delay, count=count)
    async with listening(app) as base:
        model, channels = await configured(env, admin, base)
        model = await update(
            admin,
            model,
            routing={
                **model["routing"],
                "first_response_timeout_seconds": 3,
                "stream_idle_timeout_seconds": 3,
                "total_timeout_seconds": 120,
            },
        )
        async with env.sessions() as db:
            channel = await db.get(ModelChannel, channels[0]["id"])
            channel.timeout_seconds = 3
            await db.commit()
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            response = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, stream=True)
            )
        assert response.status_code == 200, response.text
        assert "[DONE]" in response.text and '"error"' not in response.text
        assert response.text.count("part") == count
        assert len(calls) == 1
        assert (await entries(admin))[0]["status"] == "settled"
        history = (await admin.api.get(BASE + model["id"] + "/calls")).json()[0]
        assert history["duration_ms"] > minimum_ms


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first_delay", "chunk_delay", "code", "http_status"),
    [
        (4, 0, "upstream_first_response_timeout", 504),
        (0, 4, "upstream_idle_timeout", 200),
    ],
)
async def test_first_and_idle_timeout_report_cause_and_keep_uncertain_hold(
    env, monkeypatch, first_delay, chunk_delay, code, http_status
):
    admin = await env.client()
    await billing(admin)
    app, calls = provider(first_delay=first_delay, chunk_delay=chunk_delay, count=2)
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        model = await update(
            admin,
            model,
            routing={
                **model["routing"],
                "first_response_timeout_seconds": 3,
                "stream_idle_timeout_seconds": 3,
                "total_timeout_seconds": 20,
            },
        )
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            response = await api.post(
                GATEWAY, headers=bearer(token), json=payload(model, stream=True)
            )
        assert response.status_code == http_status, response.text
        assert code in response.text
        assert "[DONE]" not in response.text and len(calls) == 1
        if chunk_delay:
            assert "part" in response.text and "未返回新的输出" in response.text
        assert (await entries(admin))[0]["status"] == "review"


@pytest.mark.asyncio
async def test_explicit_total_limit_still_bounds_continuous_output():
    budget = Timeouts(0.12, 0.1, 0.1)
    received = 0
    with pytest.raises(ExecutionTimeout, match="总时长") as caught:
        while True:
            async with budget.waiting(first=not received):
                await asyncio.sleep(0.025)
            received += 1
    assert received >= 2
    assert caught.value.code == "upstream_timeout"


def test_defaults_and_migration_preserve_explicit_limits():
    policy = RoutingPolicy()
    assert policy.total_timeout_seconds == 1800
    assert policy.first_response_timeout_seconds == policy.stream_idle_timeout_seconds == 180
    assert RoutingPolicy(total_timeout_seconds=7200).total_timeout_seconds == 7200
    spec = importlib.util.spec_from_file_location(
        "timeouts_migration", Path("migrations/versions/116k_model_timeouts.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = {
        "routing": {"total_timeout_seconds": 60},
        "operations": [
            {"kind": "chat", "routing": {"total_timeout_seconds": 60}},
            {"kind": "embedding", "routing": {"total_timeout_seconds": 90}},
        ],
        "marker": "preserve",
    }
    saved = deepcopy(original)
    result = module.backfill(original)
    assert original == saved
    assert result["routing"]["total_timeout_seconds"] == 1800
    assert result["operations"][0]["routing"]["total_timeout_seconds"] == 1800
    assert result["operations"][1]["routing"]["total_timeout_seconds"] == 90
    assert result["marker"] == "preserve"
    assert module.backfill(result) == result
    explicit = {"routing": {**policy.model_dump(), "total_timeout_seconds": 60}}
    assert module.backfill(explicit) == explicit


@pytest.mark.asyncio
async def test_postgres_migration_preserves_models_and_increments_version(env):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.modules.llm.models import CatalogModel

    admin = await env.client()
    app, _ = provider()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with env.sessions() as db:
            row = await db.scalar(select(CatalogModel).where(CatalogModel.slug == model["slug"]))
            config = deepcopy(row.configuration)
            for part in [config, *(config["operations"] or [])]:
                for key in (
                    "connect_timeout_seconds",
                    "first_response_timeout_seconds",
                    "stream_idle_timeout_seconds",
                ):
                    part["routing"].pop(key, None)
                part["routing"]["total_timeout_seconds"] = 60
            row.configuration = config
            version = row.version
            await db.commit()
            spec = importlib.util.spec_from_file_location(
                "timeouts_migration", Path("migrations/versions/116k_model_timeouts.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            def upgrade(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    module.upgrade()

            await (await db.connection()).run_sync(upgrade)
            await db.refresh(row)
            assert row.version == version + 1
            assert row.configuration == module.backfill(config)
            await (await db.connection()).run_sync(upgrade)
            await db.refresh(row)
            assert row.version == version + 1
