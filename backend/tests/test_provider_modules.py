"""Actual SDK + local upstream protocol checks; no paid calls or live credentials."""

import asyncio
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from test_identity_access import env as identity_env
from test_mcp import listening

from app.core.config import Settings
from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.sdk import test_chat as run_chat

env = identity_env
pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("provider_id", ["openai", "anthropic", "gemini"])
async def test_sdk_protocol_and_usage(provider_id):
    app = FastAPI()
    calls = []
    key = "isolated-channel-key"

    @app.post("/{path:path}")
    async def respond(path: str, request: Request):
        payload = await request.json()
        calls.append((path, dict(request.headers), payload))
        if provider_id == "anthropic":
            assert path == "v1/messages"
            assert request.headers["x-api-key"] == key
            assert payload["model"] == "claude-sonnet-4-20250514"
            return {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": payload["model"],
                "content": [{"type": "text", "text": "hello"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 7, "output_tokens": 2},
            }
        if provider_id == "gemini":
            assert "generateContent" in path
            assert key in (request.query_params.get("key"), request.headers.get("x-goog-api-key"))
            assert payload["contents"][0]["parts"][0]["text"] == "hello"
            return {
                "candidates": [
                    {
                        "content": {"role": "model", "parts": [{"text": "hello"}]},
                        "finishReason": "STOP",
                        "index": 0,
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 7,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 9,
                },
            }
        assert path == "v1/chat/completions"
        assert request.headers["authorization"] == "Bearer " + key
        assert payload["model"] == "unknown-model"
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "unknown-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "hello"},
                }
            ],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        }

    async with listening(app) as url:
        module = PROVIDERS[provider_id]
        result = await run_chat(
            adapter=module.sdk_provider,
            base=url + ("/v1" if provider_id == "openai" else ""),
            key=key,
            model={
                "openai": "unknown-model",
                "anthropic": "claude-sonnet-4-20250514",
                "gemini": "gemini-2.5-flash",
            }[provider_id],
            prompt="hello",
            max_output=32,
            timeout=10,
            request_id=uuid4(),
            settings=Settings(_env_file=None, llm_allowed_private_origins=[url]),
        )
    assert result.ok, result
    assert result.output == "hello" and len(calls) == 1
    assert result.usage_source == "upstream"
    assert (result.input_tokens, result.output_tokens) == (7, 2)


async def test_sdk_concurrent_credentials_no_retry_and_no_estimated_usage():
    app = FastAPI()
    calls = []

    @app.post("/v1/chat/completions")
    async def respond(request: Request):
        auth = request.headers.get("authorization")
        calls.append(auth)
        await asyncio.sleep(0.01)
        if auth == "Bearer fail-secret":
            return JSONResponse({"error": {"message": "fail-secret"}}, status_code=429)
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": auth or "anonymous"},
                }
            ],
        }

    async with listening(app) as url:

        async def call(key):
            return await run_chat(
                adapter="openai",
                base=url + "/v1",
                key=key,
                model="test",
                prompt="hi",
                max_output=16,
                timeout=10,
                request_id=uuid4(),
                settings=Settings(_env_file=None, llm_allowed_private_origins=[url]),
            )

        first, second, failed, anonymous = await asyncio.gather(
            call("first-secret"), call("second-secret"), call("fail-secret"), call(None)
        )
    assert len(calls) == 4
    assert set(calls) == {"Bearer first-secret", "Bearer second-secret", "Bearer fail-secret", None}
    assert first.ok and second.ok and anonymous.ok and not failed.ok
    for result in (first, second, failed, anonymous):
        assert "secret" not in result.model_dump_json()
        assert result.usage_source == "unknown" and result.input_tokens is None


@pytest.mark.parametrize("provider_id", ["anthropic", "gemini"])
async def test_native_directories_preserve_partial_and_auth(provider_id):
    app = FastAPI()

    @app.get("/{path:path}")
    async def respond(path: str, request: Request):
        assert "authorization" not in request.headers
        if provider_id == "anthropic":
            assert path == "v1/models" and request.headers["x-api-key"] == "test-secret"
            return {"data": [{"id": "claude-test"}], "has_more": True}
        assert path == "v1beta/models" and request.headers["x-goog-api-key"] == "test-secret"
        return {"models": [{"name": "models/gemini-test"}], "nextPageToken": "next"}

    async with listening(app) as url:
        listing = await PROVIDERS[provider_id].list_models(
            url, "test-secret", 5, Settings(_env_file=None, llm_allowed_private_origins=[url])
        )
    assert listing.partial and len(listing.models) == 1
    assert not listing.models[0].id.startswith("models/")


async def test_module_api_authorization_and_credential_boundary(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    modules = (await admin.api.get("/api/v1/llm/providers")).json()
    assert [p["id"] for p in modules[:3]] == ["openai", "anthropic", "gemini"]
    assert (await member.api.get("/api/v1/llm/providers")).status_code == 403
    body = {
        "name": "Claude",
        "provider": "anthropic",
        "base_url": "https://example.com",
        "api_key": "native-secret",
        "models": [{"id": "claude-test"}],
    }
    row = await admin.api.post("/api/v1/llm/channels", json=body)
    assert row.status_code == 200, row.text
    data = row.json()
    path = "/api/v1/llm/channels/" + data["id"]
    changed = {**body, "provider": "openai", "version": data["version"]}
    changed.pop("api_key")
    assert (await admin.api.put(path, json=changed)).status_code == 422
    assert (
        await admin.api.post(
            "/api/v1/llm/channels",
            json={**body, "name": "无认证", "api_key": None, "auth_mode": "none"},
        )
    ).status_code == 422
    test = {"id": "claude-test", "prompt": "hi", "max_output_tokens": 16, "version": 1}
    assert (await member.api.post(path + "/test/chat", json=test)).status_code == 403
    assert (
        await admin.api.post(path + "/test/chat", json={**test, "id": "other"})
    ).status_code == 422
    assert (
        await admin.api.post(path + "/test/chat", json={**test, "version": 99})
    ).status_code == 409


async def test_channel_diagnostic_endpoint_audit_and_configuration_race(env):
    import json

    from sqlalchemy import select

    from app.modules.audit.models import AuditEvent

    admin = await env.client()
    upstream = FastAPI()
    started, release = asyncio.Event(), asyncio.Event()
    requests = []

    @upstream.post("/v1/chat/completions")
    async def respond(request: Request):
        body = await request.json()
        requests.append(body)
        if body["messages"][0]["content"] == "wait":
            started.set()
            await release.wait()
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "unknown",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "private-output"},
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        }

    async with listening(upstream) as url:
        env.provider.settings.llm_allowed_private_origins = [url]
        config = {
            "name": "SDK",
            "provider": "openai",
            "base_url": url + "/v1",
            "api_key": "private-key",
            "models": [{"id": "unknown"}],
        }
        created = await admin.api.post("/api/v1/llm/channels", json=config)
        assert created.status_code == 200, created.text
        path = "/api/v1/llm/channels/" + created.json()["id"]
        body = {"id": "unknown", "version": 1, "prompt": "private-input", "max_output_tokens": 16}
        csrf = await admin.api.post(path + "/test/chat", json=body, headers={"x-csrf-token": "bad"})
        assert csrf.status_code == 403 and not requests
        response = await admin.api.post(path + "/test/chat", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["ok"] and response.json()["input_tokens"] == 3
        pending = asyncio.create_task(
            admin.api.post(path + "/test/chat", json={**body, "prompt": "wait"})
        )
        await asyncio.wait_for(started.wait(), 10)
        edited = await admin.api.put(path, json={**config, "name": "SDK revised", "version": 1})
        assert edited.status_code == 200, edited.text
        release.set()
        assert (await pending).status_code == 409
    async with env.sessions() as db:
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.action.like("llm.channel.test.%")))
        ).all()
        assert len(events) == 4
        details = json.dumps([event.details for event in events])
        assert all(
            secret not in details for secret in ["private-key", "private-input", "private-output"]
        )
        assert sum(event.action == "llm.channel.test.finish" for event in events) == 2
        assert len({event.details["request_id"] for event in events}) == 2


async def test_sdk_outbound_boundary_no_redirect_and_transport_retry():
    import httpx
    from fastapi import HTTPException
    from fastapi.responses import RedirectResponse

    from app.modules.llm.providers.sdk_transport import RuntimeTransport

    upstream = FastAPI()
    calls = []

    @upstream.post("/{path:path}")
    async def redirect(path: str):
        calls.append(path)
        return RedirectResponse("/other", status_code=307)

    async with listening(upstream) as url:

        async def call(allowed):
            return await run_chat(
                adapter="openai",
                base=url + "/v1",
                key="test-key",
                model="unknown",
                prompt="hi",
                max_output=16,
                timeout=5,
                request_id=uuid4(),
                settings=Settings(_env_file=None, llm_allowed_private_origins=allowed),
            )

        denied = await call([])
        assert not denied.ok and not calls
        redirected = await call([url])
        assert not redirected.ok and calls == ["v1/chat/completions"]
        transport = RuntimeTransport(
            url, "test-key", Settings(_env_file=None, llm_allowed_private_origins=[url]), "openai"
        )
        try:
            with pytest.raises(HTTPException):
                await transport.handle_async_request(
                    httpx.Request("POST", url + "/v1/chat/completions", json={})
                )
            with pytest.raises(HTTPException):
                await transport.handle_async_request(
                    httpx.Request("POST", url + "/v1/chat/completions", json={})
                )
            assert len(calls) == 2
        finally:
            await transport.aclose()


async def test_router_reuse_spike_order_and_weights(monkeypatch):
    """Selection-only proof; not evidence for streaming, billing or shared cooldown."""
    from litellm import Router
    from litellm.router_strategy import simple_shuffle

    deployments = [
        {
            "model_name": "public-model",
            "litellm_params": {
                "model": "openai/unknown",
                "api_key": "test-only",
                "order": order,
                "weight": weight,
            },
            "model_info": {"id": name},
        }
        for name, order, weight in [("primary-a", 1, 1), ("primary-b", 1, 3), ("backup", 2, 100)]
    ]
    router = Router(model_list=deployments, routing_strategy="simple-shuffle", num_retries=0)
    captured = []

    def choose(population, weights):
        captured.append(weights)
        return [1]

    monkeypatch.setattr(simple_shuffle.random, "choices", choose)
    selected = router.get_available_deployment(
        model="public-model", messages=[{"role": "user", "content": "hi"}]
    )
    assert selected["model_info"]["id"] == "primary-b"
    assert captured == [[0.25, 0.75]]
