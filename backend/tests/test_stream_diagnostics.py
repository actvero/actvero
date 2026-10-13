"""Single administrator SSE diagnostics through the locked SDK and loopback HTTP."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel
from test_llm_execution import configured as configure_chat
from test_llm_execution import upstream as chat_upstream
from test_mcp import listening
from test_sdk_runtime import MODELS, fixture_provider

from app.modules.auth.service import now
from app.modules.llm.diagnostic_schemas import ChatDiagnostic, EmbeddingDiagnostic
from app.modules.llm.diagnostic_stream import DeltaRedactor
from app.modules.llm.models import ModelCall, ModelChannel, RouteHealth

pytestmark = pytest.mark.asyncio
env = identity_env


def body(version: int, model: str, *, request_id: str | None = None) -> dict:
    return {
        "version": version,
        "request_id": request_id or str(uuid4()),
        "upstream_id": model,
        "operation": "chat",
        "endpoint": "chat_completions",
        "stream": True,
        "input": {"prompt": "private-prompt", "max_output_tokens": 8},
    }


def events(value: str) -> list[tuple[str, dict]]:
    parsed = []
    for frame in value.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in frame.splitlines())
        parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


@pytest.mark.parametrize("adapter", ["openai", "anthropic", "gemini"])
async def test_real_sdk_stream_sse_usage_receipt_and_one_send(env, adapter):
    admin = await env.client()
    upstream, calls = fixture_provider(adapter)
    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            provider=adapter,
            base_url=root + ("/v1" if adapter == "openai" else ""),
            api_key="fake-key",
            models=[{"id": MODELS[adapter]}],
            declared_apis=["chat_completions"],
        )
        request = body(channel["version"], MODELS[adapter])
        endpoint = f"/api/v1/llm/channels/{channel['id']}/diagnostics"
        response = await admin.api.post(endpoint, json=request)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/event-stream")
        delivered = events(response.text)
        assert [event for event, _ in delivered][:1] == ["accepted"]
        assert [event for event, _ in delivered][-2:] == ["usage", "result"]
        assert any(event == "delta" for event, _ in delivered)
        assert delivered[-1][1]["status"] == "success"
        result = delivered[-1][1]["result"]
        assert result["stream"] is True and result["ok"] is True
        assert result["usage_source"] == "upstream"
        assert result["attempt"]["sent"] is True
        assert len(calls) == 1
        path, headers, upstream_body = calls[0]
        if adapter == "openai":
            assert path == "v1/chat/completions"
            assert upstream_body["stream"] is True
            assert upstream_body["stream_options"] == {"include_usage": True}
        elif adapter == "anthropic":
            assert path == "v1/messages" and headers["x-api-key"] == "fake-key"
            assert upstream_body["stream"] is True
        else:
            assert "streamgeneratecontent" in path.lower()
            assert headers["x-goog-api-key"] == "fake-key"
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request['request_id']}")
        assert detail.status_code == 200, detail.text
        record = detail.json()["record"]
        assert record["status"] == "success" and record["stream"] is True
        assert "private-prompt" not in detail.text
        replay = await admin.api.post(endpoint, json=request)
        assert replay.status_code == 409 and len(calls) == 1


@pytest.mark.parametrize("adapter", ["openai", "anthropic", "gemini"])
async def test_sdk_eof_delivers_unconfirmed_diagnostic_result(env, adapter):
    admin = await env.client()
    upstream, calls = fixture_provider(adapter, broken=True)
    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            provider=adapter,
            base_url=root + ("/v1" if adapter == "openai" else ""),
            api_key="fake-key",
            models=[{"id": MODELS[adapter]}],
            declared_apis=["chat_completions"],
        )
        request = body(channel["version"], MODELS[adapter])
        response = await admin.api.post(
            f"/api/v1/llm/channels/{channel['id']}/diagnostics", json=request
        )
        assert response.status_code == 200, response.text
        delivered = events(response.text)
        assert delivered[-1][0] == "result"
        assert delivered[-1][1]["status"] == "unconfirmed"
        assert not delivered[-1][1]["result"]["ok"]
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request['request_id']}")
        assert detail.json()["record"]["status"] == "unconfirmed"
        assert detail.json()["record"]["attempt"]["sent"] is True
        assert len(calls) == 1


async def test_schema_rejects_non_chat_stream_and_redacts_split_key():
    request = body(1, "test-model")
    assert ChatDiagnostic.model_validate(request).stream is True
    with pytest.raises(ValueError):
        EmbeddingDiagnostic.model_validate(
            {
                **request,
                "operation": "embedding",
                "endpoint": "embeddings",
                "input": {"input": ["x"]},
            }
        )
    redactor = DeltaRedactor("secret-key")
    parts = [
        redactor.delta({"content": "start secret"}),
        redactor.delta({"content": "-key end"}),
        redactor.flush(),
    ]
    delivered = "".join(part.get("content", "") for part in parts)
    assert "secret-key" not in delivered
    assert delivered == "start 〈已隐藏密钥〉 end"
    for key in ("aaa", "abcab"):
        for split in range(1, len(key)):
            redactor = DeltaRedactor(key)
            parts = [
                redactor.delta({"content": "before " + key[:split]}),
                redactor.delta({"content": key[split:] + " after"}),
                redactor.flush(),
            ]
            delivered = "".join(part.get("content", "") for part in parts)
            assert delivered == "before 〈已隐藏密钥〉 after"
    redactor = DeltaRedactor("]")
    delivered = redactor.delta({"content": "a]b"})["content"] + redactor.flush().get("content", "")
    assert "]" not in delivered


@pytest.mark.parametrize("change", ["version", "permission", "session"])
async def test_channel_change_between_deltas_stops_output(env, change):
    admin = await env.client()
    other = await env.client(tenant=admin.tenant) if change != "version" else admin
    upstream = FastAPI()
    between = asyncio.Event()
    resume = asyncio.Event()
    calls = []

    @upstream.post("/{path:path}")
    async def reply(path: str, request: Request):
        calls.append((path, await request.json()))

        async def source():
            def item(delta: dict, finish: str | None = None) -> str:
                return (
                    "data: "
                    + json.dumps(
                        {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}
                    )
                    + "\n\n"
                )

            yield item({"role": "assistant", "content": "first"})
            between.set()
            await resume.wait()
            yield item({"content": "should-not-leak"})
            yield item({}, "stop")
            yield (
                "data: "
                + json.dumps({"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 2}})
                + "\n\n"
            )
            yield "data: [DONE]\n\n"

        return StreamingResponse(source(), media_type="text/event-stream")

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            base_url=root + "/v1",
            api_key="fake-key",
            models=[{"id": "test-model"}],
            declared_apis=["chat_completions"],
        )
        request = body(channel["version"], "test-model")
        task = asyncio.create_task(
            admin.api.post(f"/api/v1/llm/channels/{channel['id']}/diagnostics", json=request)
        )
        await asyncio.wait_for(between.wait(), 5)
        async with env.sessions() as db:
            if change == "version":
                row = await db.get(ModelChannel, UUID(channel["id"]))
                assert row is not None
                row.version += 1
            else:
                # A second administrator remains; simulate revocation while
                # the response is already open without relying on a new login.
                from app.modules.members.models import Membership

                member = await db.get(Membership, admin.member.id)
                assert member is not None
                if change == "permission":
                    member.role = "member"
                else:
                    member.revoked_at = now()
            await db.commit()
        resume.set()
        response = await task
        assert response.status_code == 200
        delivered = events(response.text)
        assert delivered[-1][0] == "error"
        assert delivered[-1][1]["status_code"] == (
            409 if change == "version" else 403 if change == "permission" else 401
        )
        if change == "session":
            assert "重新登录" in delivered[-1][1]["message"]
        assert "should-not-leak" not in response.text
        assert not any(name == "result" for name, _ in delivered)
        detail = await other.api.get(f"/api/v1/llm/diagnostics/{request['request_id']}")
        assert detail.json()["record"]["status"] == "unconfirmed"
        assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 429])
async def test_upstream_rejection_is_distinct_from_platform_permission(env, status):
    admin = await env.client()
    upstream, calls = fixture_provider("openai", status=status)
    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            base_url=root + "/v1",
            api_key="fake-key",
            models=[{"id": "test-model"}],
            declared_apis=["chat_completions"],
        )
        request = body(channel["version"], "test-model")
        response = await admin.api.post(
            f"/api/v1/llm/channels/{channel['id']}/diagnostics", json=request
        )
        assert response.status_code == 200
        delivered = events(response.text)
        assert delivered[-1][0] == "error"
        assert delivered[-1][1]["status_code"] == (429 if status == 429 else 502)
        assert "private-upstream-secret" not in response.text
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request['request_id']}")
        record = detail.json()["record"]
        assert record["status"] == "failure"
        assert record["attempt"]["upstream_status"] == status
        assert record["attempt"]["upstream_terminal"] is True
        assert len(calls) == 1


@pytest.mark.parametrize("broken", [False, True])
async def test_stream_health_certification_requires_complete_upstream(env, broken):
    admin = await env.client()
    upstream, state = chat_upstream()
    state["broken"] = broken
    async with listening(upstream) as root:
        model, channels = await configure_chat(env, admin, root)
        selected = channels[0]
        request = {
            **body(selected["version"], "vendor-chat"),
            "certify_health": True,
            "model_id": model["id"],
            "model_version": model["version"],
            "binding_id": model["bindings"][0]["binding_id"],
        }
        response = await admin.api.post(
            f"/api/v1/llm/channels/{selected['id']}/diagnostics", json=request
        )
        assert response.status_code == 200, response.text
        delivered = events(response.text)
        assert delivered[-1][0] == "result"
        assert delivered[-1][1]["status"] == ("unconfirmed" if broken else "success")
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request['request_id']}")
        record = detail.json()["record"]
        assert record["status"] == ("unconfirmed" if broken else "success")
        assert record["health_certification"] == ("not_certified" if broken else "certified")
        async with env.sessions() as db:
            health = list(await db.scalars(select(RouteHealth)))
            assert health
            assert any(item.tested_at is not None for item in health) is (not broken)
        assert len(state["calls"]) == 1


async def test_cancelled_stream_preserves_partial_usage_and_no_certification(env):
    admin = await env.client()
    upstream = FastAPI()
    partial = asyncio.Event()
    release = asyncio.Event()
    calls = []

    @upstream.post("/{path:path}")
    async def reply(path: str, request: Request):
        calls.append((path, await request.json()))

        async def source():
            yield (
                "data: "
                + json.dumps(
                    {
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": "partial"},
                                "finish_reason": None,
                            }
                        ]
                    }
                )
                + "\n\n"
            )
            yield (
                "data: "
                + json.dumps({"choices": [], "usage": {"prompt_tokens": 2, "completion_tokens": 1}})
                + "\n\n"
            )
            partial.set()
            await release.wait()
            yield "data: [DONE]\n\n"

        return StreamingResponse(source(), media_type="text/event-stream")

    async with listening(upstream) as root:
        model, channels = await configure_chat(env, admin, root)
        selected = channels[0]
        request = {
            **body(selected["version"], "vendor-chat"),
            "certify_health": True,
            "model_id": model["id"],
            "model_version": model["version"],
            "binding_id": model["bindings"][0]["binding_id"],
        }
        endpoint = f"/api/v1/llm/channels/{selected['id']}/diagnostics"
        task = asyncio.create_task(admin.api.post(endpoint, json=request))
        await asyncio.wait_for(partial.wait(), 5)
        await asyncio.sleep(0.05)  # Let the SDK consume the two already-sent SSE frames.
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request['request_id']}")
        assert detail.status_code == 200, detail.text
        record = detail.json()["record"]
        assert record["status"] == "unconfirmed"
        assert record["health_certification"] == "not_certified"
        assert record["attempt"]["sent"] is True
        assert record["attempt"]["upstream_terminal"] is False
        assert record["attempt"]["error_code"] == "caller_cancelled"
        assert any(
            entry["field"] == "raw_prompt_tokens" and entry["value"] == 2
            for entry in record["attempt"]["usage_evidence"]
        )
        async with env.sessions() as db:
            call = await db.get(ModelCall, UUID(request["request_id"]))
            assert call is not None and call.status == "unknown"
            health = list(await db.scalars(select(RouteHealth)))
            assert health and all(item.tested_at is None for item in health)
        assert (await admin.api.post(endpoint, json=request)).status_code == 409
        assert len(calls) == 1
