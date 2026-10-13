"""Channel control plane: real PostgreSQL, isolated identities and loopback upstream."""

import asyncio
import gzip
import json
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select
from test_identity_access import env as identity_env
from test_mcp import listening

from app.core.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.llm.models import ModelChannel
from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.base import ModelListing
from app.modules.llm.providers.openai_compatible import OpenAICompatible
from app.modules.llm.schemas import UpstreamModel

env = identity_env

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/channels"
CONFIG = {"name": "团队渠道", "base_url": "https://example.com/v1", "api_key": "test-secret"}


async def create(admin, **kwargs):
    response = await admin.api.post(BASE, json=CONFIG | kwargs)
    assert response.status_code == 200, response.text
    return response.json()


async def test_secrets_and_authorization(env):
    admin = await env.client()
    row = await create(admin)
    path = BASE + "/" + row["id"]
    assert row["credential_configured"] and row["last_check"] is None
    assert row["model_count"] == 0 and not row["archived"]
    for url in [BASE, path, "/api/v1/llm/providers"]:
        response = await admin.api.get(url)
        assert response.status_code == 200
        assert "test-secret" not in response.text and "sealed_key" not in response.text
    async with env.sessions() as db:
        stored = await db.get(ModelChannel, UUID(row["id"]))
        assert stored.sealed_key != "test-secret"
        assert env.provider.unseal(stored.sealed_key) == {"key": "test-secret"}
        events = (await db.scalars(select(AuditEvent))).all()
        assert all("test-secret" not in json.dumps(e.details) for e in events)
    member = await env.client(role="member", tenant=admin.tenant)
    for method, url, data in [
        ("GET", BASE, None),
        ("GET", path, None),
        ("GET", "/api/v1/llm/providers", None),
        ("POST", BASE, CONFIG),
        ("POST", path + "/discover", {"version": 1}),
        ("PUT", path, CONFIG | {"version": 1}),
        ("POST", path + "/models", {"version": 1, "models": [{"id": "m"}]}),
        ("PUT", path + "/archive", {"version": 1, "archived": True}),
    ]:
        assert (await member.api.request(method, url, json=data)).status_code == 403
    assert (
        await admin.api.post(BASE, json=CONFIG, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    assert (await admin.api.get(BASE + "/" + str(uuid4()))).status_code == 404
    admin.api.cookies.clear()
    assert (await admin.api.get(BASE)).status_code == 401
    assert (
        await admin.api.get(BASE, headers={"authorization": "Bearer desktop-token"})
    ).status_code == 401


async def test_edit_credentials_concurrency_and_archive(env):
    admin = await env.client()
    row = await create(admin)
    path = BASE + "/" + row["id"]
    body = {"name": "新的名称", "base_url": CONFIG["base_url"], "version": 1}
    results = await asyncio.gather(*[admin.api.put(path, json=body) for _ in range(2)])
    assert sorted(r.status_code for r in results) == [200, 409]
    changed = body | {"version": 2, "base_url": "https://other.example/v1"}
    assert (await admin.api.put(path, json=changed)).status_code == 422
    response = await admin.api.put(path, json=changed | {"api_key": "new-secret"})
    assert response.status_code == 200 and response.json()["credential_configured"]
    response = await admin.api.put(path, json=changed | {"version": 3, "auth_mode": "none"})
    assert response.status_code == 200 and not response.json()["credential_configured"]
    archived = await admin.api.put(path + "/archive", json={"version": 4, "archived": True})
    assert archived.status_code == 200
    assert (await admin.api.get(BASE)).json()["total"] == 0
    assert (await admin.api.get(BASE + "?state=archived")).json()["total"] == 1
    assert (await admin.api.post(path + "/check", json={"version": 5})).status_code == 409
    assert (
        await admin.api.put(path + "/archive", json={"version": 5, "archived": False})
    ).status_code == 200


async def test_preview_registration_and_failure_preserve_models(env, monkeypatch):
    admin = await env.client()
    row = await create(admin)
    path = BASE + "/" + row["id"]
    upstream = AsyncMock(
        return_value=ModelListing([UpstreamModel(id="model-a"), UpstreamModel(id="model-b")])
    )
    monkeypatch.setattr(PROVIDERS["openai-compatible"], "list_models", upstream)
    response = await admin.api.post(path + "/discover", json={"version": 1})
    preview = response.json()
    assert preview["ok"] and preview["channel"]["models"] == []
    body = {"version": 2, "snapshot_id": preview["snapshot_id"], "models": [{"id": "not-returned"}]}
    assert (await admin.api.post(path + "/models", json=body)).status_code == 409
    body["models"] = [{"id": "model-a"}]
    saved = await admin.api.post(path + "/models", json=body)
    assert saved.status_code == 200 and saved.json()["model_count"] == 1
    upstream.side_effect = HTTPException(502, "上游拒绝认证")
    failed = (await admin.api.post(path + "/discover", json={"version": 3})).json()
    assert not failed["ok"] and failed["channel"]["models"][0]["id"] == "model-a"
    manual = await admin.api.post(
        path + "/models", json={"version": 4, "models": [{"id": "manual"}, {"id": "model-a"}]}
    )
    assert manual.json()["model_count"] == 2
    assert manual.json()["models"][0]["source"] == "discovery"
    upstream.side_effect = None
    upstream.return_value = ModelListing([])
    empty = (await admin.api.post(path + "/discover", json={"version": 5})).json()
    assert empty["ok"] and empty["candidates"] == [] and empty["channel"]["model_count"] == 2
    removed = await admin.api.request(
        "DELETE", path + "/models", json={"version": 6, "models": [{"id": "manual"}]}
    )
    assert removed.json()["model_count"] == 1


async def test_inflight_result_cannot_overwrite_new_config_or_revoked_admin(env, monkeypatch):
    admin = await env.client()
    other = await env.client(tenant=admin.tenant)
    row = await create(admin)
    path = BASE + "/" + row["id"]
    started, finish = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await finish.wait()
        return ModelListing([UpstreamModel(id="stale")])

    monkeypatch.setattr(PROVIDERS["openai-compatible"], "list_models", slow)
    task = asyncio.create_task(admin.api.post(path + "/discover", json={"version": 1}))
    await asyncio.wait_for(started.wait(), 5)
    assert (
        await other.api.put(path, json=CONFIG | {"version": 1, "name": "Changed"})
    ).status_code == 200
    finish.set()
    assert (await task).status_code == 409
    assert (await admin.api.get(path)).json()["checks"] == []
    started.clear()
    finish.clear()
    task = asyncio.create_task(admin.api.post(path + "/check", json={"version": 2}))
    await asyncio.wait_for(started.wait(), 5)
    async with env.sessions() as db:
        member = await db.get(type(admin.member), admin.member.id)
        member.role = "member"
        await db.commit()
    finish.set()
    assert (await task).status_code == 403
    assert (await other.api.get(path)).json()["checks"] == []


@pytest.mark.parametrize(
    "mode", ["ok", "empty", "401", "redirect", "invalid", "huge", "echo", "compressed"]
)
async def test_real_metadata_http_has_no_inference_or_redirects(mode):
    app = FastAPI()
    calls = []

    @app.get("/v1/models")
    async def models(request: Request):
        calls.append(request.url.path)
        assert request.headers["authorization"] == "Bearer fixture-key"
        assert not request.headers.get("cookie")
        if mode == "401":
            return Response("fixture-key", status_code=401)
        if mode == "redirect":
            return RedirectResponse("/leak")
        if mode == "invalid":
            return JSONResponse({"data": [{"name": "missing-id"}]})
        if mode == "huge":
            return Response(b"x" * 2_000_001)
        if mode == "compressed":
            return Response(gzip.compress(b"x" * 2_000_001), headers={"Content-Encoding": "gzip"})
        if mode == "echo":
            return JSONResponse({"data": [{"id": "fixture-key"}]})
        return JSONResponse(
            {
                "data": [] if mode == "empty" else [{"id": "model"}, {"id": "model"}],
                "has_more": mode == "ok",
            }
        )

    async with listening(app) as url:
        settings = Settings(_env_file=None, llm_allowed_private_origins=[url])
        if mode in {"ok", "empty"}:
            listing = await OpenAICompatible().list_models(url + "/v1", "fixture-key", 5, settings)
            assert len(listing.models) == (1 if mode == "ok" else 0)
            assert listing.partial == (mode == "ok")
        else:
            with pytest.raises(HTTPException) as error:
                await OpenAICompatible().list_models(url + "/v1", "fixture-key", 5, settings)
            assert "fixture-key" not in error.value.detail
        assert calls == ["/v1/models"]
        with pytest.raises(HTTPException):
            await OpenAICompatible().list_models(
                url + "/v1",
                "fixture-key",
                5,
                Settings(_env_file=None, mcp_allowed_private_origins=[url]),
            )
        assert calls == ["/v1/models"]


async def test_draft_inspection_has_real_transport_and_never_saves_configuration(env):
    admin = await env.client()
    upstream = FastAPI()
    calls = []

    @upstream.get("/v1/models")
    async def models(request: Request):
        calls.append(request.headers.get("authorization"))
        return {"data": [{"id": "model-a"}, {"id": "model-b"}], "has_more": True}

    async with listening(upstream) as url:
        body = {"base_url": url + "/v1", "api_key": "draft-secret", "discover": True}
        # The draft path must use the same independent SSRF rules as saved channels.
        denied = await admin.api.post("/api/v1/llm/channel-drafts/inspect", json=body)
        assert denied.status_code == 200 and not denied.json()["ok"]
        assert not calls
        env.provider.settings.llm_allowed_private_origins = [url]
        result = await admin.api.post("/api/v1/llm/channel-drafts/inspect", json=body)
        assert result.status_code == 200, result.text
        assert result.json()["ok"] and result.json()["partial"]
        assert result.json()["candidates"] == [{"id": "model-a"}, {"id": "model-b"}]
        assert calls == ["Bearer draft-secret"]
        assert "draft-secret" not in result.text
        assert (await admin.api.get(BASE)).json()["total"] == 0
        checked = await admin.api.post(
            "/api/v1/llm/channel-drafts/inspect", json=body | {"discover": False}
        )
        assert checked.json()["ok"] and checked.json()["candidates"] == []
        member = await env.client(role="member", tenant=admin.tenant)
        assert (
            await member.api.post("/api/v1/llm/channel-drafts/inspect", json=body)
        ).status_code == 403
        assert (
            await admin.api.post(
                "/api/v1/llm/channel-drafts/inspect", json=body, headers={"x-csrf-token": "bad"}
            )
        ).status_code == 403
        assert len(calls) == 2
    async with env.sessions() as db:
        assert not (await db.scalars(select(ModelChannel))).all()
        events = (await db.scalars(select(AuditEvent))).all()
        assert len(events) == 3
        assert all("draft-secret" not in json.dumps(event.details) for event in events)


async def test_edit_draft_uses_only_own_unchanged_destination_and_rechecks_version(
    env, monkeypatch
):
    admin = await env.client()
    row = await create(admin)
    endpoint = "/api/v1/llm/channel-drafts/inspect"
    body = {"base_url": CONFIG["base_url"], "channel_id": row["id"], "version": 1, "discover": True}
    upstream = AsyncMock(return_value=ModelListing([UpstreamModel(id="model-a")]))
    monkeypatch.setattr(PROVIDERS["openai-compatible"], "list_models", upstream)
    response = await admin.api.post(endpoint, json=body)
    assert response.status_code == 200 and response.json()["ok"]
    assert upstream.call_args.args[:3] == (CONFIG["base_url"], "test-secret", 20)
    unchanged = (await admin.api.get(BASE + "/" + row["id"])).json()
    assert unchanged["version"] == 1 and unchanged["checks"] == [] and unchanged["models"] == []
    for invalid, status in [
        ({"base_url": "https://different.example/v1"}, 422),
        ({"channel_id": str(uuid4())}, 404),
        ({"version": 2}, 409),
        ({"version": None}, 422),
    ]:
        assert (await admin.api.post(endpoint, json=body | invalid)).status_code == status
    assert upstream.call_count == 1
    started, finish = asyncio.Event(), asyncio.Event()

    async def slow(*args, **kwargs):
        started.set()
        await finish.wait()
        return ModelListing([UpstreamModel(id="stale")])

    monkeypatch.setattr(PROVIDERS["openai-compatible"], "list_models", slow)
    task = asyncio.create_task(admin.api.post(endpoint, json=body))
    await asyncio.wait_for(started.wait(), 5)
    other = await env.client(tenant=admin.tenant)
    assert (
        await other.api.put(BASE + "/" + row["id"], json=CONFIG | {"version": 1, "name": "Changed"})
    ).status_code == 200
    finish.set()
    assert (await task).status_code == 409
    started.clear()
    finish.clear()
    task = asyncio.create_task(admin.api.post(endpoint, json=body | {"version": 2}))
    await asyncio.wait_for(started.wait(), 5)
    async with env.sessions() as db:
        member = await db.get(type(admin.member), admin.member.id)
        member.role = "member"
        await db.commit()
    finish.set()
    assert (await task).status_code == 403
    assert (await other.api.get(BASE + "/" + row["id"])).json()["models"] == []


async def test_configuration_saves_models_atomically_and_preserves_existing_provenance(env):
    admin = await env.client()
    row = await create(admin, models=[{"id": "a"}, {"id": "b"}, {"id": "a"}])
    assert row["model_count"] == 2
    assert [model["source"] for model in row["models"]] == ["configuration", "configuration"]
    path = BASE + "/" + row["id"]
    original = row["models"][0]
    # Failed configuration validation cannot partially rename or replace inventory.
    bad = await admin.api.put(
        path, json=CONFIG | {"name": "Invalid", "version": 1, "models": [{"id": "bad id"}]}
    )
    assert bad.status_code == 422
    duplicate = await create(admin, name="Occupied")
    assert duplicate["id"] != row["id"]
    conflict = await admin.api.put(
        path, json=CONFIG | {"name": "Occupied", "version": 1, "models": []}
    )
    assert conflict.status_code == 409
    assert (await admin.api.get(path)).json()["models"] == row["models"]
    changed = await admin.api.put(
        path, json=CONFIG | {"version": 1, "models": [{"id": "a"}, {"id": "c"}]}
    )
    assert changed.status_code == 200
    assert changed.json()["models"][0] == original
    assert [model["id"] for model in changed.json()["models"]] == ["a", "c"]
    assert (
        await admin.api.put(path, json=CONFIG | {"version": 1, "models": []})
    ).status_code == 409
    kept = await admin.api.put(path, json=CONFIG | {"version": 2})
    assert kept.json()["model_count"] == 2
    cleared = await admin.api.put(path, json=CONFIG | {"version": 3, "models": []})
    assert cleared.json()["models"] == []
