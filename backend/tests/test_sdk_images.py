"""Image diagnostics: real LiteLLM, loopback upstream, isolated DB and bounded media."""

import asyncio
import base64
import json
from io import BytesIO
from uuid import UUID

import httpx2
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from PIL import Image
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_mcp import listening

from app.core.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.llm import image_delivery
from app.modules.llm.models import CatalogModel, ModelChannel
from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk_images import generate
from app.modules.llm.schemas import ChannelImageProbe

env = identity_env
pytestmark = pytest.mark.asyncio


def raster(format="PNG", size=(8, 8)):
    output = BytesIO()
    Image.new("RGB", size, "red").save(output, format=format)
    return output.getvalue()


def data_image():
    return {"b64_json": base64.b64encode(raster()).decode()}


def probe():
    return {
        "version": 1,
        "id": "opaque/model",
        "operation": "image_generation",
        "prompt": "private prompt",
    }


async def create(admin, url, provider="openai-compatible"):
    res = await admin.api.post(
        "/api/v1/llm/channels",
        json={
            "name": "Image probe " + provider,
            "provider": provider,
            "base_url": url + "/custom/v2",
            "api_key": "private-key",
            "models": [{"id": "opaque/model"}],
            "declared_apis": [],
        },
    )
    assert res.status_code == 200, res.text
    return "/api/v1/llm/channels/" + res.json()["id"]


@pytest.mark.parametrize("provider,usage", [("openai", True), ("openai-compatible", False)])
async def test_image_probe_sdk_delivery_history_and_no_publication(env, provider, usage):
    admin = await env.client()
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def reply(path: str, request: Request):
        calls.append((path, dict(request.headers), await request.json()))
        return {
            "created": 123,
            "data": [data_image()],
            **(
                {
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 17,
                        "total_tokens": 28,
                        "input_tokens_details": {"image_tokens": 0, "text_tokens": 11},
                    }
                }
                if usage
                else {}
            ),
        }

    async with listening(app) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url, provider)
        res = await admin.api.post(
            path + "/test",
            json={**probe(), "size": "1024x1024", "quality": "high"},
        )
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    assert "img-src 'self' data: blob:;" in res.headers["content-security-policy"]
    assert "script-src 'self';" in res.headers["content-security-policy"]
    data = res.json()
    assert data["ok"] and data["image_count"] == 1 and not data["uncertain"], data
    assert data["image"] == {
        **data_image(),
        "media_type": "image/png",
        "width": 8,
        "height": 8,
        "bytes": len(raster()),
    }
    assert data["input_tokens"] == (11 if usage else None)
    assert data["output_tokens"] == (17 if usage else None)
    assert data["usage_source"] == ("upstream" if usage else "unknown")
    assert len(calls) == 1
    target, headers, body = calls[0]
    assert target == "custom/v2/images/generations"
    assert headers["authorization"] == "Bearer private-key"
    assert body == {
        "model": "opaque/model",
        "prompt": "private prompt",
        "n": 1,
        "size": "1024x1024",
        "quality": "high",
    }
    history = (await admin.api.get(path + "/tests")).json()[0]
    assert history["operation"] == "image_generation" and history["image_count"] == 1
    assert history["status"] == "success" and "image" not in history
    attempt = history["attempt"]
    assert attempt["attempt_id"] == data["attempt"]["attempt_id"]
    assert attempt["sent"] and attempt["upstream_terminal"] and attempt["output_started"]
    assert attempt["client_terminal"] is None
    counts = [entry for entry in attempt["usage_evidence"] if entry["field"] == "image_count"]
    assert len(counts) == 1 and counts[0]["value"] == 1
    assert counts[0]["source"] == "confirmed_delivery" and counts[0]["complete"]
    async with env.sessions() as db:
        channel = await db.get(ModelChannel, UUID(path.split("/")[-1]))
        assert channel.version == 1 and channel.declared_apis == [] and channel.checks == []
        assert await db.scalar(select(func.count()).select_from(CatalogModel)) == 0
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.action.like("llm.channel.test.%")))
        ).all()
        assert len(events) == 2
        raw = json.dumps([e.details for e in events])
        for secret in ["private prompt", "private-key", data_image()["b64_json"]]:
            assert secret not in raw
        assert events[0].details["size"] == "1024x1024"


@pytest.mark.parametrize(
    "status,images",
    [
        (429, None),
        (200, []),
        (200, [{"b64_json": "eA=="}]),
        (200, [{"url": "https://127.0.0.1/image?private-token=secret"}]),
    ],
)
async def test_image_failure_one_attempt_sanitized_and_raw_meters_preserved(env, status, images):
    admin = await env.client()
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def reply(path: str):
        calls.append(path)
        return JSONResponse(
            {"error": {"message": "private-key"}}
            if status != 200
            else {
                "created": 123,
                "data": images,
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 7,
                    "total_tokens": 12,
                    "input_tokens_details": {"image_tokens": 0, "text_tokens": 5},
                },
            },
            status_code=status,
        )

    async with listening(app) as url:
        env.provider.settings.llm_allowed_private_origins = [url, "https://127.0.0.1"]
        path = await create(admin, url)
        res = await admin.api.post(path + "/test", json=probe())
    assert res.status_code == 200, res.text
    data = res.json()
    assert not data["ok"] and data["image"] is None and len(calls) == 1
    assert data["image_count"] is None
    assert not any(entry["field"] == "image_count" for entry in data["attempt"]["usage_evidence"])
    assert all(secret not in res.text for secret in ["private-key", "private-token", "127.0.0.1"])
    assert data["uncertain"] == (status == 200)
    if status == 200 and images:
        assert data["input_tokens"] == 5 and data["output_tokens"] == 7
        assert data["error_code"] == "image_delivery_failed"
        assert data["attempt"]["error_scope"] == "delivery"
        assert data["attempt"]["upstream_status"] == 200
    assert (await admin.api.get(path + "/tests")).json()[0]["status"] == "failure"


async def test_image_probe_permissions_limits_and_module_boundary(env):
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
        ({"n": 2}, 422),
        ({"prompt": " "}, 422),
        ({"prompt": "x" * 2001}, 422),
        ({"size": "999999x999999"}, 422),
        ({"quality": "invalid"}, 422),
    ]:
        assert (
            await admin.api.post(path + "/test", json={**probe(), **change})
        ).status_code == status
    native = await create(admin, "https://example.test", "gemini")
    assert (await admin.api.post(native + "/test", json=probe())).status_code == 422
    for name, module in PROVIDERS.items():
        assert ("image_generation" in module.info.member_operations) == (
            name in ["openai", "openai-compatible"]
        )
        assert ("image_generation" in module.info.test_operations) == (
            name in ["openai", "openai-compatible"]
        )


async def test_image_cancellation_leaves_unconfirmed_history(env):
    admin = await env.client()
    app = FastAPI()
    started, release = asyncio.Event(), asyncio.Event()

    @app.post("/{path:path}")
    async def reply(path: str):
        started.set()
        await release.wait()
        return {"data": [data_image()]}

    async with listening(app) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        path = await create(admin, url)
        task = asyncio.create_task(admin.api.post(path + "/test", json=probe()))
        await asyncio.wait_for(started.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
    row = (await admin.api.get(path + "/tests")).json()[0]
    assert row["status"] == "unconfirmed" and row["uncertain"] and row["input_tokens"] is None


async def test_image_timeout_does_not_retry():
    app, calls = FastAPI(), []
    release = asyncio.Event()

    @app.post("/{path:path}")
    async def reply(path: str):
        calls.append(path)
        await release.wait()
        return {"data": [data_image()]}

    async with listening(app) as url:
        try:
            with pytest.raises(UpstreamFailure) as error:
                await generate(
                    ChannelImageProbe.model_validate(probe()),
                    url,
                    None,
                    1,
                    Settings(llm_allowed_private_origins=[url]),
                )
            assert error.value.uncertain and error.value.code == "upstream_timeout"
            assert len(calls) == 1
        finally:
            release.set()


@pytest.mark.parametrize(
    "format,mime", [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")]
)
async def test_raster_formats(format, mime):
    content = raster(format)
    result = await image_delivery.deliver_image(
        {"b64_json": base64.b64encode(content).decode()}, Settings()
    )
    assert result.media_type == mime and result.bytes == len(content)


@pytest.mark.parametrize(
    "value",
    [
        {"b64_json": "garbage"},
        {"url": "http://example.test/image"},
        {"url": "https://x:y@example.test/image"},
        {"url": "https://169.254.169.254/secret"},
        {"url": "https://[::1]/image"},
        {"b64_json": "eA==", "url": "https://example.test/image"},
        {"b64_json": base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode()},
    ],
)
async def test_bad_media_never_delivered(value):
    with pytest.raises(UpstreamFailure) as error:
        await image_delivery.deliver_image(value, Settings())
    assert error.value.code == "image_delivery_failed" and error.value.uncertain
    assert error.value.health_failure is False


async def test_size_and_pixel_limits(monkeypatch):
    monkeypatch.setattr(image_delivery, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(UpstreamFailure):
        await image_delivery.deliver_image(data_image(), Settings())
    monkeypatch.setattr(image_delivery, "MAX_IMAGE_BYTES", 8_000_000)
    monkeypatch.setattr(image_delivery, "MAX_PIXELS", 4)
    with pytest.raises(UpstreamFailure):
        await image_delivery.deliver_image(data_image(), Settings())


@pytest.mark.parametrize(
    "status,encoding,oversized",
    [
        (200, "identity", False),
        (302, "identity", False),
        (200, "gzip", False),
        (200, "identity", True),
    ],
)
async def test_image_fetch_pins_host_preserves_signature_and_has_no_credentials(
    monkeypatch, status, encoding, oversized
):
    calls = []
    original = image_delivery.PinnedTransport

    async def lookup(bare, allowed, *, dns):
        assert bare == "https://cdn.example.test/image.png" and allowed == []
        return "93.184.216.34"

    async def serve(request):
        calls.append(request)
        assert str(request.url) == "https://93.184.216.34/image.png?sig=private-signature"
        assert request.headers["host"] == "cdn.example.test"
        assert request.extensions["sni_hostname"] == "cdn.example.test"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        assert request.headers["accept-encoding"] == "identity"
        # Encoding is checked before reading/decompression, so raw bytes are deliberate.
        return httpx2.Response(
            status,
            headers={"content-encoding": encoding, "location": "https://127.0.0.1/secret"},
            stream=httpx2.ByteStream(raster()),
        )

    class Transport(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.inner = httpx2.MockTransport(serve)

    monkeypatch.setattr(image_delivery, "resolve", lookup)
    monkeypatch.setattr(image_delivery, "PinnedTransport", Transport)
    if oversized:
        monkeypatch.setattr(image_delivery, "MAX_IMAGE_BYTES", 10)
    value = {"url": "https://cdn.example.test/image.png?sig=private-signature"}
    if status == 200 and encoding == "identity" and not oversized:
        result = await image_delivery.deliver_image(value, Settings())
        assert result.media_type == "image/png"
    else:
        with pytest.raises(UpstreamFailure):
            await image_delivery.deliver_image(value, Settings())
    assert len(calls) == 1
