"""Member speech uses real SDK / loopback audio, permissions and the shared ledger."""

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from llm_billing_helpers import billing
from sqlalchemy import select
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import bearer, native_client
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel
from test_llm_execution import credentials
from test_llm_routing import update
from test_mcp import listening
from test_sdk_speech import audio

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import ModelCall, UsageSettlement

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/models/"
GATEWAY = "/api/llm/v1"
PRICE = {"currency": "USD", "metric": "characters", "unit": 1000, "input": "0.5"}


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


def upstream(reply=None):
    app, calls = FastAPI(), []

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        calls.append((dict(request.headers), await request.json()))
        return reply if reply is not None else Response(audio(), media_type="audio/wav")

    return app, calls


async def configure(admin, base, *, enabled=True):
    channel = await create_channel(
        admin, base_url=base + "/v1", models=[{"id": "opaque/speech"}], declared_apis=["speech"]
    )
    operation = {
        "kind": "speech",
        "enabled": enabled,
        "channel_id": channel["id"],
        "upstream_id": "opaque/speech",
        "speech": {"voice": "private-voice", "max_input_characters": 100},
        "budget_price": PRICE,
        "bindings": [
            {
                "channel_id": channel["id"],
                "upstream_id": "opaque/speech",
                "enabled": enabled,
                "price": {**PRICE, "input": "0.1"},
            }
        ],
    }
    res = await admin.api.post(
        BASE.rstrip("/"),
        json={
            "name": "团队语音",
            "slug": "team-speech",
            "access": {"enabled": enabled, "audience": "organization"},
            "operations": [operation],
        },
    )
    assert res.status_code == 200, res.text
    return res.json()


async def test_speech_key_directory_raw_wav_exact_characters_and_private_logs(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        directory = (await api.get(GATEWAY + "/models", headers=headers(key))).json()["data"][0]
        assert directory["kind"] == "speech" and directory["output_modalities"] == ["audio"]
        assert directory["speech"]["voice"] == "private-voice"
        assert directory["metric"] == "characters"
        assert "budget_price" not in json.dumps(directory) and "channel_id" not in json.dumps(
            directory
        )
        body = {"model": model["slug"], "input": "你好👋!"}
        res = await api.post(
            GATEWAY + "/audio/speech",
            json=body,
            headers={**headers(key), "idempotency-key": "speech-once"},
        )
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "audio/wav" and res.content == audio()
        assert res.headers["cache-control"] == "no-store"
        duplicate = await api.post(
            GATEWAY + "/audio/speech",
            json=body,
            headers={**headers(key), "idempotency-key": "speech-once"},
        )
        assert duplicate.status_code == 409 and len(calls) == 1
        assert calls[0][1] == {
            "model": "opaque/speech",
            "input": body["input"],
            "voice": "private-voice",
            "response_format": "wav",
        }
        async with env.sessions() as db:
            log = await db.scalar(select(ModelCall))
            entry = await db.scalar(select(UsageSettlement))
            assert log.kind == "speech" and log.source == "access_key"
            assert entry.status == "settled" and entry.amount == Decimal("0.002")
            assert entry.reserved_amount == entry.amount
            assert log.usage["input_characters"] == 4
            assert log.usage["supplier_usage_source"] == "unknown"
            assert log.usage["billing_source"] == "platform_input_characters"
            assert Decimal(log.estimates["procurement"]["amount"]) == Decimal("0.0004")
            raw = json.dumps([log.usage, log.attempts, entry.usage], ensure_ascii=False)
            assert body["input"] not in raw and "private-voice" not in raw
        history = (await admin.api.get("/api/v1/llm/settlements")).json()["items"][0]
        assert history["metric"] == "characters" and history["kind"] == "speech"


@pytest.mark.parametrize(
    "change",
    [
        {"voice": "other"},
        {"response_format": "mp3"},
        {"input": "x" * 101},
        {"input": " "},
        {"stream": True},
        {"speed": 2},
        {"api_key": "override"},
    ],
)
async def test_speech_invalid_parameters_before_admission(env, change):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        await configure(admin, base)
        res = await api.post(
            GATEWAY + "/audio/speech",
            json={"model": "team-speech", "input": "hi", **change},
            headers=headers(key),
        )
        assert res.status_code == 422, res.text
        assert not calls
        async with env.sessions() as db:
            assert await db.scalar(select(UsageSettlement)) is None


async def test_speech_draft_admin_test_csrf_does_not_publish_or_charge_member(env):
    admin, member = await env.client(), await env.client(role="member")
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base, enabled=False)
        body = {"model": model["slug"], "input": "hi"}
        assert (
            await api.post(GATEWAY + "/audio/speech", json=body, headers=headers(key))
        ).status_code == 404
        assert (
            await member.api.post(BASE + model["id"] + "/test/speech", json=body)
        ).status_code == 403
        assert (
            await admin.api.post(
                BASE + model["id"] + "/test/speech", json=body, headers={"x-csrf-token": "bad"}
            )
        ).status_code == 403
        res = await admin.api.post(
            BASE + model["id"] + "/test/speech",
            json=body,
            params={
                "channel_id": model["bindings"][0]["channel_id"],
                "upstream_id": "opaque/speech",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["audio"]["duration_ms"] == 100 and len(calls) == 1
        assert not (await admin.api.get(BASE + model["id"])).json()["access"]["enabled"]
        async with env.sessions() as db:
            assert await db.scalar(select(UsageSettlement)) is None


@pytest.mark.parametrize(
    "reply",
    [
        JSONResponse({"error": {"message": "private-error"}}, status_code=429),
        Response(b"broken", media_type="audio/wav"),
    ],
)
async def test_speech_uncertain_failure_keeps_reservation_for_reconciliation(env, reply):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream(reply)
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        await configure(admin, base)
        res = await api.post(
            GATEWAY + "/audio/speech",
            json={"model": "team-speech", "input": "hi"},
            headers=headers(key),
        )
        assert res.status_code in (429, 502) and len(calls) == 1
        assert "private-error" not in res.text
        entry = (await admin.api.get("/api/v1/llm/settlements")).json()["items"][0]
        assert entry["status"] == "review" and entry["points"] is None
        assert Decimal(entry["reserved_points"]) == Decimal("0.1")
        assert "input_characters" not in entry["usage"]


async def test_speech_atomic_quota_and_live_member_permissions(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin, points="0.1")
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        body = {"model": model["slug"], "input": "hi"}
        results = await asyncio.gather(
            *[
                api.post(GATEWAY + "/audio/speech", json=body, headers=headers(key))
                for _ in range(2)
            ]
        )
        assert sorted(r.status_code for r in results) == [200, 429] and len(calls) == 1
        await update(admin, model, access={**model["access"], "audience": "administrators"})
        assert (
            await api.post(GATEWAY + "/audio/speech", json=body, headers=headers(key))
        ).status_code == 404


async def test_speech_draft_and_price_rules():
    config = {"slug": "s", "name": "s", "operations": [{"kind": "speech"}]}
    assert not CatalogInput.model_validate(config).operation_configs()[0].enabled
    for changed in [
        {"budget_price": {"currency": "USD", "input": "1"}},
        {"routing": {"mode": "auto"}},
    ]:
        with pytest.raises(ValueError):
            CatalogInput.model_validate({**config, "operations": [{"kind": "speech", **changed}]})


async def test_speech_desktop_shares_key_budget_and_scope(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin, points="0.25")
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        root, token = await credentials(env, monkeypatch, api, member, model)
        body = {"model": model["slug"], "input": "hello"}
        assert (
            await api.post(GATEWAY + "/audio/speech", json=body, headers=bearer(root))
        ).status_code == 401
        result = await api.post(GATEWAY + "/audio/speech", json=body, headers=bearer(token))
        assert result.status_code == 200, result.text
        assert (
            await api.post(GATEWAY + "/audio/speech", json=body, headers=headers(key))
        ).status_code == 429
        assert len(calls) == 1
        mine = await api.get("/api/v1/desktop/llm/usage", headers=bearer(root))
        assert mine.status_code == 200, mine.text
        assert "procurement" not in mine.text and "USD" not in mine.text
        async with env.sessions() as db:
            log = await db.scalar(select(ModelCall))
            assert log.source == "desktop" and log.device_id is not None


@pytest.mark.parametrize("cancel", [False, True])
async def test_speech_revocation_and_cancellation_after_send(env, monkeypatch, cancel):

    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    entered, release = asyncio.Event(), asyncio.Event()
    from app.modules.llm.providers.sdk_router import Invocation

    original = Invocation.call

    async def delayed(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(Invocation, "call", delayed)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        pending = asyncio.create_task(
            api.post(
                GATEWAY + "/audio/speech",
                json={"model": model["slug"], "input": "hi"},
                headers=headers(key),
            )
        )
        await asyncio.wait_for(entered.wait(), 5)
        if cancel:
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            release.set()
        else:
            await update(admin, model, access={**model["access"], "audience": "administrators"})
            release.set()
            res = await pending
            assert res.status_code == 404 and res.headers["content-type"] != "audio/wav"
        assert len(calls) == 1
        async with env.sessions() as db:
            entry = await db.scalar(select(UsageSettlement))
            log = await db.scalar(select(ModelCall))
            assert entry.status == ("review" if cancel else "settled")
            if cancel:
                assert entry.amount is None and entry.reserved_amount == Decimal("0.001")
                assert log.termination_code == "caller_cancelled"
            else:
                assert entry.amount == Decimal("0.001")
