"""Real LiteLLM multipart / loopback upstream / isolated ledger and permissions."""

import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from llm_billing_helpers import billing
from sqlalchemy import select
from test_access_keys import create as create_key
from test_access_keys import headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel
from test_llm_routing import update
from test_mcp import listening
from test_sdk_speech import audio

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.models import ModelCall, UsageSettlement

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/models/"
GATEWAY = "/api/llm/v1/audio/transcriptions"
PRICE = {"currency": "USD", "metric": "seconds", "unit": 1, "input": "0.2"}


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


def upstream(reply=None):
    app, calls = FastAPI(), []

    @app.post("/v1/audio/transcriptions")
    async def transcribe(request: Request):
        async with request.form() as form:
            file = form["file"]
            calls.append(
                {
                    "model": form.get("model"),
                    "format": form.get("response_format"),
                    "language": form.get("language"),
                    "filename": file.filename,
                    "audio": await file.read(),
                    "headers": dict(request.headers),
                }
            )
        return (
            reply
            if reply is not None
            else JSONResponse(
                {
                    "text": "你好 world",
                    "segments": [{"start": 0, "end": 0.1, "text": "你好 world", "tokens": [1, 2]}],
                    "usage": {"seconds": 1},
                }
            )
        )

    return app, calls


async def configure(admin, base, enabled=True):
    channel = await create_channel(
        admin,
        base_url=base + "/v1",
        models=[{"id": "opaque/transcribe"}],
        declared_apis=["transcriptions"],
    )
    response = await admin.api.post(
        BASE.rstrip("/"),
        json={
            "name": "团队转写",
            "slug": "team-stt",
            "access": {"enabled": enabled, "audience": "organization"},
            "operations": [
                {
                    "kind": "transcription",
                    "enabled": enabled,
                    "channel_id": channel["id"],
                    "upstream_id": "opaque/transcribe",
                    "transcription": {"max_duration_seconds": 30, "timestamps": True},
                    "budget_price": PRICE,
                    "bindings": [
                        {
                            "channel_id": channel["id"],
                            "upstream_id": "opaque/transcribe",
                            "enabled": enabled,
                            "price": PRICE,
                        }
                    ],
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def upload(model, **kwargs):
    return {
        "files": {"file": ("private-personal-name.wav", audio(), "audio/wav")},
        "data": {"model": model["slug"], **kwargs},
    }


async def test_transcription_real_sdk_multipart_usage_and_no_content_in_logs(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        params = upload(model, language="zh", response_format="verbose_json")
        r = await api.post(
            GATEWAY, **params, headers={**headers(key), "idempotency-key": "stt-once"}
        )
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["text"] == "你好 world"
        assert result["segments"] == [{"start": 0.0, "end": 0.1, "text": "你好 world"}]
        assert result["usage"] == {
            "supplier_usage_source": "upstream",
            "supplier_usage": {"seconds": 1},
            "audio_duration_ms": 100,
            "billing_source": "platform_audio_duration",
        }
        duplicate = await api.post(
            GATEWAY, **params, headers={**headers(key), "idempotency-key": "stt-once"}
        )
        assert duplicate.status_code == 409 and len(calls) == 1
        assert calls[0]["model"] == "opaque/transcribe" and calls[0]["format"] == "verbose_json"
        assert calls[0]["filename"] == "audio.wav" and calls[0]["audio"] == audio()
        assert calls[0]["language"] == "zh"
        async with env.sessions() as db:
            entry = await db.scalar(select(UsageSettlement))
            assert entry.status == "settled" and entry.amount == Decimal("0.02")
            log = await db.scalar(select(ModelCall))
            assert "private-personal" not in json.dumps(log.attempts)
            assert "world" not in json.dumps(log.attempts)
        directory = (await api.get("/api/llm/v1/models", headers=headers(key))).json()["data"][0]
        assert directory["kind"] == "transcription" and directory["metric"] == "seconds"
        assert directory["input_modalities"] == ["audio"] and directory["output_modalities"] == [
            "text"
        ]
        assert directory["unit"] == 1 and directory["transcription"]["timestamps"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("stream", "true"),
        ("response_format", "srt"),
        ("language", "not-a-language"),
        ("api_key", "evil"),
        ("prompt", "hidden"),
        ("file", "https://private/"),
    ],
)
async def test_invalid_parameters_never_call_or_reserve(env, field, value):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        r = await api.post(GATEWAY, **upload(model, **{field: value}), headers=headers(key))
        assert r.status_code in (400, 422), r.text
        assert calls == []
        async with env.sessions() as db:
            assert await db.scalar(select(UsageSettlement)) is None
            assert await db.scalar(select(ModelCall)) is None


@pytest.mark.parametrize("content", [b"fake-wav", b"RIFF" + b"\x00" * 8100000])
async def test_invalid_oversize_audio_rejected(env, content):
    member = await env.client(role="member")
    key, _ = await create_key(member)
    async with native_client(env) as api:
        r = await api.post(
            GATEWAY,
            files={"file": ("file.wav", content)},
            data={"model": "team-stt"},
            headers=headers(key),
        )
        assert r.status_code in (413, 422), r.text


@pytest.mark.parametrize(
    "reply",
    [
        JSONResponse({"text": ""}),
        JSONResponse({"not_text": "bad"}),
        JSONResponse({"error": {"message": "private upstream secret"}}, status_code=429),
    ],
)
async def test_silence_valid_failures_hold_reservation(env, reply):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream(reply)
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        r = await api.post(GATEWAY, **upload(model), headers=headers(key))
        success = reply.body == b'{"text":""}'
        assert r.status_code == (200 if success else 429 if reply.status_code == 429 else 502), (
            r.text
        )
        assert len(calls) == 1 and "private upstream secret" not in r.text
        async with env.sessions() as db:
            entry = await db.scalar(select(UsageSettlement))
            assert entry.status == ("settled" if success else "review")
            assert entry.amount == (Decimal(".02") if success else None)
        if success:
            assert (
                r.json()["text"] == "" and r.json()["usage"]["supplier_usage_source"] == "unknown"
            )


async def test_disabled_model_admin_test_does_not_open_or_charge_and_csrf(env):
    admin, member = await env.client(), await env.client(role="member")
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base, enabled=False)
        url = (
            BASE
            + model["id"]
            + "/test/transcriptions?channel_id="
            + model["bindings"][0]["channel_id"]
            + "&upstream_id=opaque/transcribe"
        )
        r = await api.post(GATEWAY, **upload(model), headers=headers(key))
        assert r.status_code == 404
        r = await member.api.post(url, **upload(model))
        assert r.status_code == 403
        r = await admin.api.post(url, **upload(model), headers={"X-CSRF-Token": "bad"})
        assert r.status_code == 403
        r = await admin.api.post(url, **upload(model))
        assert r.status_code == 200, r.text
        assert len(calls) == 1
        async with env.sessions() as db:
            assert await db.scalar(select(UsageSettlement)) is None
        r = await api.post(GATEWAY, **upload(model), headers=headers(key))
        assert r.status_code == 404


@pytest.mark.parametrize("cancel", [True, False])
async def test_transcription_cancel_and_revocation_after_send(env, monkeypatch, cancel):

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
        task = asyncio.create_task(api.post(GATEWAY, **upload(model), headers=headers(key)))
        await asyncio.wait_for(entered.wait(), 5)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            release.set()
        else:
            await update(admin, model, access={**model["access"], "audience": "administrators"})
            release.set()
            response = await task
            assert response.status_code == 404 and "world" not in response.text
        assert len(calls) == 1
        async with env.sessions() as db:
            entry = await db.scalar(select(UsageSettlement))
            assert entry.status == ("review" if cancel else "settled")
            assert entry.amount == (None if cancel else Decimal(".02"))


async def test_transcription_requires_declared_timestamps_and_duration_limits(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        model = await update(
            admin,
            model,
            operations=[
                {
                    **model["operations"][0],
                    "transcription": {"max_duration_seconds": 1, "timestamps": False},
                }
            ],
        )
        response = await api.post(
            GATEWAY, **upload(model, response_format="verbose_json"), headers=headers(key)
        )
        assert response.status_code == 422, response.text
        response = await api.post(
            GATEWAY,
            files={"file": ("long.wav", audio(frames=8800))},
            data={"model": model["slug"]},
            headers=headers(key),
        )
        assert response.status_code == 422, response.text
        assert not calls


async def test_transcription_desktop_and_key_share_atomic_quota(env, monkeypatch):
    from test_desktop import bearer
    from test_llm_execution import credentials

    admin, member = await env.client(), await env.client(role="member")
    await billing(admin, points="2")
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        root, token = await credentials(env, monkeypatch, api, member, model)
        assert (await api.post(GATEWAY, **upload(model), headers=bearer(root))).status_code == 401
        results = await asyncio.gather(
            api.post(GATEWAY, **upload(model), headers=bearer(token)),
            api.post(GATEWAY, **upload(model), headers=headers(key)),
        )
        assert sorted(r.status_code for r in results) == [200, 429]
        assert len(calls) == 1


@pytest.mark.parametrize("action", ["settle", "release"])
async def test_audio_reconciliation_uses_explicit_milliseconds_and_keeps_member_privacy(
    env, action
):
    admin, member = await env.client(), await env.client(role="member")
    outsider = await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream(JSONResponse({"error": {"message": "busy"}}, status_code=429))
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        assert (await api.post(GATEWAY, **upload(model), headers=headers(key))).status_code == 429
        listing = await admin.api.get("/api/v1/llm/settlements")
        assert listing.status_code == 200, listing.text
        entry = listing.json()["items"][0]
        assert entry["metric"] == "seconds" and entry["status"] == "review"
        url = "/api/v1/llm/settlements/" + entry["id"] + "/reconcile"
        body = {"version": entry["version"], "action": action, "reason": "核对供应商账单"}
        invalid = await admin.api.post(url, json={**body, "usage": {"input": 100}})
        assert invalid.status_code == 422
        invalid = await admin.api.post(url, json={**body, "audio_duration_ms": 120001})
        assert invalid.status_code == 422
        if action == "settle":
            assert (await admin.api.post(url, json=body)).status_code == 422
            body["usage"] = {"metric": "seconds", "audio_duration_ms": 100}
            body["request_id"] = str(uuid4())
        else:
            invalid = await admin.api.post(url, json={**body, "audio_duration_ms": 0})
            assert invalid.status_code == 422
        assert (await member.api.post(url, json=body)).status_code == 403
        result = await admin.api.post(url, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["items"][0]["status"] == (
            "settled" if action == "settle" else "released"
        )
        assert (await admin.api.post(url, json=body)).status_code == (
            200 if action == "settle" else 409
        )
        history = await member.api.get("/api/v1/account/llm/usage")
        assert history.status_code == 200
        own = history.json()["items"][0]
        assert own["points"] == ("2" if action == "settle" else "0")
        assert own["reason"] == "" and "USD" not in history.text
        assert "price" not in own and "amount" not in own
        assert (await outsider.api.get("/api/v1/account/llm/usage")).json()["total"] == 0
        assert len(calls) == 1
