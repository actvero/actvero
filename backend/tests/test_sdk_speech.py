"""TTS diagnostics use the real SDK, a loopback supplier and isolated database."""

import asyncio
import base64
import json
import struct
import wave
from io import BytesIO
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_mcp import listening

from app.core.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.llm.audio_delivery import deliver_audio
from app.modules.llm.models import CatalogModel, ModelChannel
from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk_speech import generate
from app.modules.llm.schemas import ChannelSpeechProbe

env = identity_env
pytestmark = pytest.mark.asyncio


def audio(frames=800, channels=1, rate=8000, width=2):
    output = BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(width)
        target.setframerate(rate)
        target.writeframes(b"\0" * frames * channels * width)
    return output.getvalue()


def probe():
    return {
        "version": 1,
        "id": "opaque/tts",
        "operation": "speech",
        "input": "private spoken text",
        "voice": "private-voice",
        "response_format": "wav",
    }


async def create(admin, url, provider="openai-compatible", auth=True):
    res = await admin.api.post(
        "/api/v1/llm/channels",
        json={
            "name": "Speech probe " + provider,
            "provider": provider,
            "base_url": url + "/custom/v2",
            "auth_mode": "api_key" if auth else "none",
            **({"api_key": "private-key"} if auth else {}),
            "models": [{"id": "opaque/tts"}],
            "declared_apis": [],
        },
    )
    assert res.status_code == 200, res.text
    return "/api/v1/llm/channels/" + res.json()["id"]


@pytest.mark.parametrize(
    "provider,auth", [("openai", True), ("openai-compatible", True), ("openai-compatible", False)]
)
async def test_speech_sdk_delivery_privacy_and_no_publication(env, provider, auth):
    admin = await env.client()
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def reply(path: str, request: Request):
        calls.append((path, dict(request.headers), await request.json()))
        return Response(audio(), media_type="audio/wav")

    async with listening(app) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url, provider, auth)
        res = await admin.api.post(path + "/test", json=probe())
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["ok"] and not result["uncertain"], result
    assert result["usage_source"] == "unknown"
    assert result["input_tokens"] is None and result["output_tokens"] is None
    assert result["audio_duration_ms"] == 100
    assert result["audio"] == {
        "b64_json": base64.b64encode(audio()).decode(),
        "media_type": "audio/wav",
        "bytes": len(audio()),
        "duration_ms": 100,
        "sample_rate": 8000,
        "channels": 1,
    }
    assert len(calls) == 1
    target, headers, body = calls[0]
    assert target == "custom/v2/audio/speech"
    assert headers.get("authorization") == ("Bearer private-key" if auth else None)
    assert body == {
        "model": "opaque/tts",
        "input": "private spoken text",
        "voice": "private-voice",
        "response_format": "wav",
    }
    assert res.headers["cache-control"] == "no-store"
    assert "media-src 'self' blob:;" in res.headers["content-security-policy"]
    assert "script-src 'self';" in res.headers["content-security-policy"]
    history = (await admin.api.get(path + "/tests")).json()[0]
    assert history["operation"] == "speech" and history["status"] == "success"
    assert history["audio_duration_ms"] == 100 and "audio" not in history
    attempt = history["attempt"]
    assert attempt["attempt_id"] == result["attempt"]["attempt_id"]
    assert attempt["sent"] and attempt["upstream_terminal"] and attempt["output_started"]
    assert attempt["client_terminal"] is None
    assert attempt["usage_evidence"] == []  # File duration is not provider billing usage.
    async with env.sessions() as db:
        row = await db.get(ModelChannel, UUID(path.split("/")[-1]))
        assert row.version == 1 and row.declared_apis == [] and row.checks == []
        assert await db.scalar(select(func.count()).select_from(CatalogModel)) == 0
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.action.like("llm.channel.test.%")))
        ).all()
        assert len(events) == 2
        raw = json.dumps([e.details for e in events])
        for secret in [
            "private spoken text",
            "private-voice",
            "private-key",
            result["audio"]["b64_json"],
        ]:
            assert secret not in raw


@pytest.mark.parametrize(
    "failure", ["429", "redirect", "json", "html", "compressed", "truncated", "oversize", "sse"]
)
async def test_speech_failure_no_retry_and_sanitized(env, failure):
    admin = await env.client()
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def reply(path: str):
        calls.append(path)
        if failure == "429":
            return JSONResponse({"error": {"message": "private-key"}}, status_code=429)
        if failure == "redirect":
            return Response(
                status_code=307, headers={"location": "https://example.test/private-key"}
            )
        if failure == "json":
            return JSONResponse({"url": "https://example.test/private-key"})
        if failure == "html":
            return Response(b"<script>private-key</script>", media_type="audio/wav")
        if failure == "sse":
            return Response(b"data: private-key\n\n", media_type="text/event-stream")
        return Response(
            b"x" * 8_000_001
            if failure == "oversize"
            else audio()[:-10]
            if failure == "truncated"
            else audio(),
            media_type="audio/wav",
            headers={"content-encoding": "gzip"} if failure == "compressed" else {},
        )

    async with listening(app) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        res = await admin.api.post(path + "/test", json=probe())
    assert res.status_code == 200, res.text
    data = res.json()
    assert not data["ok"] and data["audio"] is None and len(calls) == 1
    assert "private-key" not in res.text
    assert data["audio_duration_ms"] is None and data["usage_source"] == "unknown"
    assert data["uncertain"] == (failure not in ["429", "redirect"])
    if data["error_code"] == "audio_delivery_failed":
        assert data["attempt"]["error_scope"] == "delivery"
    assert (await admin.api.get(path + "/tests")).json()[0]["status"] == "failure"


async def test_speech_permission_validation_and_module_boundary(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    path = await create(admin, "https://example.test")
    for actor in [member, outsider]:
        assert (await actor.api.post(path + "/test", json=probe())).status_code == 403
    assert (
        await admin.api.post(path + "/test", json=probe(), headers={"x-csrf-token": "bad"})
    ).status_code == 403
    for change, status in [
        ({"version": 2}, 409),
        ({"id": "missing"}, 422),
        ({"voice": ""}, 422),
        ({"voice": "a\r\nx-secret: yep"}, 422),
        ({"voice": {"id": "voice_123"}}, 422),
        ({"response_format": "mp3"}, 422),
        ({"input": " "}, 422),
        ({"input": "x" * 1001}, 422),
        ({"stream": True}, 422),
        ({"speed": 1.0}, 422),
        ({"api_key": "override"}, 422),
    ]:
        assert (
            await admin.api.post(path + "/test", json={**probe(), **change})
        ).status_code == status
    native = await create(admin, "https://example.test", "gemini")
    assert (await admin.api.post(native + "/test", json=probe())).status_code == 422
    for name, module in PROVIDERS.items():
        assert ("speech" in module.info.member_operations) == (
            name in ["openai", "openai-compatible"]
        )
        assert ("speech" in module.info.test_operations) == (
            name in ["openai", "openai-compatible"]
        )


async def test_speech_cancellation_and_change_during_request(env):
    admin = await env.client()
    app = FastAPI()
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    @app.post("/{path:path}")
    async def reply(path: str):
        calls.append(path)
        started.set()
        await release.wait()
        return Response(audio(), media_type="audio/wav")

    async with listening(app) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        task = asyncio.create_task(admin.api.post(path + "/test", json=probe()))
        await asyncio.wait_for(started.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        history = (await admin.api.get(path + "/tests")).json()[0]
        assert history["status"] == "unconfirmed" and history["uncertain"]
        release.set()
        started.clear()
        release.clear()
        task = asyncio.create_task(admin.api.post(path + "/test", json=probe()))
        await asyncio.wait_for(started.wait(), 10)
        async with env.sessions() as db:
            row = await db.get(ModelChannel, UUID(path.split("/")[-1]))
            row.version += 1
            await db.commit()
        release.set()
        res = await task
        assert res.status_code == 409 and "b64_json" not in res.text
        assert (await admin.api.get(path + "/tests")).json()[0]["stale"]
        assert len(calls) == 2


async def test_speech_deadline_is_bounded_and_private_origin_is_blocked():
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def reply(path: str):
        calls.append(path)
        await asyncio.sleep(0.3)
        return Response(audio(), media_type="audio/wav")

    async with listening(app) as url:
        body = ChannelSpeechProbe.model_validate(probe())
        with pytest.raises(UpstreamFailure) as result:
            await generate(
                body, url + "/v1", None, 0.1, Settings(llm_allowed_private_origins=[url])
            )
        assert result.value.uncertain and result.value.status_code == 504
        assert len(calls) == 1
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as blocked:
            await generate(body, url + "/v1", None, 1, Settings(llm_allowed_private_origins=[]))
        assert blocked.value.status_code == 422 and len(calls) == 1


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"ID3invalid",
        audio()[:-1],
        audio(rate=4000),
        audio(channels=3),
        audio(frames=0),
        audio(frames=8000 * 121),
        b"x" * 8_000_001,
    ],
)
async def test_invalid_or_excessive_audio_is_not_delivered(content):
    with pytest.raises(UpstreamFailure) as result:
        deliver_audio(content)
    assert result.value.uncertain and result.value.code == "audio_delivery_failed"
    assert result.value.health_failure is False


async def test_normalizes_metadata_and_accepts_pcm_variants():
    for channels in [1, 2]:
        for width in [1, 2, 3, 4]:
            content = audio(channels=channels, width=width)
            extra = b"JUNK" + struct.pack("<I", 14) + b"private-secret"
            content = (
                content[:4] + struct.pack("<I", len(content) + len(extra) - 8) + content[8:] + extra
            )
            output = deliver_audio(content)
            assert output.channels == channels and output.duration_ms == 100
            assert b"private-secret" not in base64.b64decode(output.b64_json)


async def test_speech_result_is_not_delivered_after_admin_revocation(env):
    from app.modules.members.models import Membership

    admin = await env.client()
    app = FastAPI()
    started, release = asyncio.Event(), asyncio.Event()

    @app.post("/{path:path}")
    async def reply(path: str):
        started.set()
        await release.wait()
        return Response(audio(), media_type="audio/wav")

    async with listening(app) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        task = asyncio.create_task(admin.api.post(path + "/test", json=probe()))
        await asyncio.wait_for(started.wait(), 10)
        async with env.sessions() as db:
            membership = await db.get(Membership, admin.member.id)
            membership.role = "member"
            await db.commit()
        release.set()
        res = await task
    assert res.status_code == 403 and "b64_json" not in res.text
    async with env.sessions() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "llm.channel.test.start")
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "llm.channel.test.finish")
            )
            == 0
        )


async def test_concurrent_speech_clients_never_share_credentials():
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def reply(path: str, request: Request):
        payload = await request.json()
        calls.append((payload["voice"], request.headers.get("authorization")))
        await asyncio.sleep(0.05)
        return Response(audio(), media_type="application/octet-stream")

    async with listening(app) as url:
        results = await asyncio.gather(
            *[
                generate(
                    ChannelSpeechProbe.model_validate({**probe(), "voice": f"voice-{index}"}),
                    url + "/v1",
                    f"key-{index}",
                    2,
                    Settings(llm_allowed_private_origins=[url]),
                )
                for index in range(2)
            ]
        )
    assert len(results) == 2 and all(r.duration_ms == 100 for r in results)
    assert sorted(calls) == [("voice-0", "Bearer key-0"), ("voice-1", "Bearer key-1")]
