"""Gateway boundaries and native contracts using isolated PostgreSQL schemas."""

from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from test_identity_access import env as identity_env

from app.core.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.auth.service import COOKIE
from app.modules.model_gateway import client, service
from app.modules.model_gateway.config import NewApiConnection
from app.modules.model_gateway.models import GatewayDirectory
from app.modules.model_gateway.schemas import GatewayChannelInput

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/model-gateway"


def bind(env, admin):
    env.provider.settings.session_cookie_name = COOKIE
    env.provider.settings.newapi_connections = [
        NewApiConnection(
            tenant_id=admin.tenant.id,
            base_url="https://gateway.example",
            management_token=SecretStr("secret-management"),
        )
    ]


def channel(**updates):
    return {
        "id": 4,
        "name": "Supplier",
        "type": 1,
        "key": "supplier-secret",
        "base_url": "https://api.example",
        "models": "public-model",
        "group": "default",
        "model_mapping": '{"public-model":"upstream-model"}',
        "status": 1,
        "priority": 0,
        "weight": 1,
        "created_time": 100,
        "setting": '{"native_flag":true}',
        **updates,
    }


async def test_gateway_requires_organization_admin_and_csrf(env, monkeypatch):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    bind(env, admin)
    call = AsyncMock()
    monkeypatch.setattr(client, "call", call)
    for actor in (member, outsider):
        assert (await actor.api.get(BASE + "/channels")).status_code == 403
    for headers in ({"x-csrf-token": "wrong"}, {"origin": "https://foreign.example"}):
        assert (
            await admin.api.post(BASE + "/channels/4/status", json={"status": 2}, headers=headers)
        ).status_code == 403
    call.assert_not_awaited()


async def test_connections_are_tenant_bound_and_not_shared():
    first, second = uuid4(), uuid4()
    values = [
        {
            "tenant_id": str(first),
            "base_url": "https://gateway.example",
            "management_token": "secret",
        },
        {
            "tenant_id": str(second),
            "base_url": "https://gateway.example/",
            "management_token": "other",
        },
    ]
    with pytest.raises(ValidationError, match="must not be shared"):
        Settings(_env_file=None, newapi_connections=values)


async def test_mapping_preserves_native_settings_and_never_returns_key(env, monkeypatch):
    admin = await env.client()
    bind(env, admin)
    row = channel()
    writes = []

    async def native(request, tenant_id, method, path, **kwargs):
        assert tenant_id == admin.tenant.id
        if method == "PUT":
            writes.append(deepcopy(kwargs["payload"]))
            row.update(kwargs["payload"])
            return None
        return deepcopy(row)

    monkeypatch.setattr(client, "call", native)
    revision = service.channel_view(row)["revision"]
    response = await admin.api.put(
        BASE + "/mappings",
        json={
            "channel_id": 4,
            "model_name": "alias",
            "upstream_id": "supplier-model",
            "revision": revision,
        },
    )
    assert response.status_code == 200, response.text
    assert writes[0]["models"] == "public-model,alias"
    assert writes[0]["setting"] == row["setting"]
    assert all(key not in writes[0] for key in ("status", "key", "channel_info"))
    assert "supplier-secret" not in response.text
    assert "setting" not in response.json()["data"]
    response = await admin.api.put(
        BASE + "/mappings",
        json={"channel_id": 4, "model_name": "alias", "upstream_id": "wrong", "revision": revision},
    )
    assert response.status_code == 409
    assert len(writes) == 1
    async with env.sessions() as db:
        events = list(await db.scalars(select(AuditEvent)))
        assert "supplier-secret" not in repr([e.__dict__ for e in events])


async def test_directory_persists_and_connection_edit_invalidates(env, monkeypatch):
    admin = await env.client()
    bind(env, admin)
    row = channel()
    fetches = 0

    async def native(request, tenant_id, method, path, **kwargs):
        nonlocal fetches
        assert tenant_id == admin.tenant.id
        if "fetch_models" in path:
            fetches += 1
            return ["upstream-model", "another"]
        if method == "PUT":
            row.update(kwargs["payload"])
            return None
        return deepcopy(row)

    monkeypatch.setattr(client, "call", native)
    assert (await admin.api.post(BASE + "/channels/4/directory", json={})).status_code == 200
    for _ in range(2):
        r = await admin.api.get(BASE + "/channels/4/directory")
        assert r.json()["models"] == ["upstream-model", "another"]
        assert r.json()["fetched_at"]
    assert fetches == 1
    body = GatewayChannelInput(
        name="Supplier",
        type=1,
        base_url="https://new.example",
        models=["public-model"],
        revision=service.channel_view(row)["revision"],
    )
    r = await admin.api.put(BASE + "/channels/4", json=body.model_dump(mode="json"))
    assert r.status_code == 200, r.text
    assert (await admin.api.get(BASE + "/channels/4/directory")).json()["models"] == []
    async with env.sessions() as db:
        assert await db.get(GatewayDirectory, (admin.tenant.id, 4)) is None


async def test_model_revision_ignores_derived_connections():
    row = {"id": 1, "model_name": "model", "status": 1}
    assert (
        service.model_view(row)["revision"]
        == service.model_view(
            {
                **row,
                "bound_channels": [{"name": "a", "type": 1}],
                "configured_channel_count": 1,
                "square_state": "visible",
            }
        )["revision"]
    )


async def test_price_uses_native_unit_and_projects_only_requested_data(env, monkeypatch):
    admin = await env.client()
    bind(env, admin)
    calls = []

    async def native(request, tenant_id, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/api/status":
            return {"quota_per_unit": 250000, "unrelated": "not-for-browser"}
        return {
            "entries": [{"model_name": "model", "version": "v1", "configured": {"ModelRatio": 1}}],
            "empty_version": "empty",
            "options": {"other-model": "hidden"},
        }

    monkeypatch.setattr(client, "call", native)
    r = await admin.api.get(BASE + "/prices?model=model")
    assert r.status_code == 200
    assert r.json()["data"]["quota_per_unit"] == 250000
    assert "options" not in r.json()["data"]
    assert calls[0][2]["params"] == {"model": "model"}


async def test_native_newapi_management_round_trip(env):
    """Opt-in contract test; removes only the uniquely named records it creates."""
    import json
    import os

    token = os.getenv("ACTVERO_TEST_NEWAPI_TOKEN")
    base = os.getenv("ACTVERO_TEST_NEWAPI_URL")
    if not token or not base:
        pytest.skip("ACTVERO_TEST_NEWAPI_TOKEN required for the pinned local New API instance")
    admin = await env.client()
    bind(env, admin)
    env.provider.settings.newapi_connections = [
        NewApiConnection(
            tenant_id=admin.tenant.id,
            base_url=base,
            management_token=SecretStr(token),
        )
    ]
    env.provider.settings.llm_allowed_private_origins = [base]
    name = "actvero-contract-" + uuid4().hex[:12]
    model_id = channel_id = None
    try:
        r = await admin.api.post(BASE + "/models", json={"model_name": name})
        assert r.status_code == 200, r.text
        model_id = r.json()["data"]["id"]
        r = await admin.api.get(BASE + "/models", params={"q": name})
        row = next(x for x in r.json()["data"]["items"] if x["model_name"] == name)
        r = await admin.api.put(
            BASE + f"/models/{model_id}",
            json={
                "model_name": name,
                "description": "contract verification",
                "revision": row["revision"],
            },
        )
        assert r.status_code == 200, r.text
        r = await admin.api.post(
            BASE + "/channels",
            json={
                "name": name,
                "type": 1,
                "base_url": "https://example.com",
                "key": "contract-test-not-a-real-key",
                "models": [name],
            },
        )
        assert r.status_code == 200, r.text
        r = await admin.api.get(BASE + "/channels", params={"q": name})
        row = next(x for x in r.json()["data"]["items"] if x["name"] == name)
        channel_id = row["id"]
        assert "key" not in row
        r = await admin.api.put(
            BASE + "/mappings",
            json={
                "channel_id": channel_id,
                "model_name": name,
                "upstream_id": "contract-upstream",
                "revision": row["revision"],
            },
        )
        assert r.status_code == 200, r.text
        assert json.loads(r.json()["data"]["model_mapping"])[name] == "contract-upstream"
        r = await admin.api.get(BASE + "/prices", params={"model": name})
        assert r.status_code == 200, r.text
        snapshot = r.json()["data"]
        entry = next(x for x in snapshot["entries"] if x["model_name"] == name)
        r = await admin.api.put(
            BASE + "/prices",
            json={
                "model_name": name,
                "expected_version": entry["version"],
                "pricing": {
                    "ModelRatio": 1.25,
                    "CompletionRatio": 4,
                    "billing_setting.billing_mode": "ratio",
                },
            },
        )
        assert r.status_code == 200, r.text
        r = await admin.api.get(BASE + "/prices", params={"model": name})
        assert r.json()["data"]["entries"][0]["effective"]["ModelRatio"] == 1.25
        r = await admin.api.post(BASE + f"/channels/{channel_id}/status", json={"status": 2})
        assert r.status_code == 200, r.text
    finally:
        if channel_id:
            response = await admin.api.delete(BASE + f"/channels/{channel_id}")
            assert response.status_code == 200, response.text
        if model_id:
            response = await admin.api.post(
                BASE + f"/models/{model_id}/delete", json={"remove_pricing": True}
            )
            assert response.status_code == 200, response.text


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("confirmed", [False, True])
async def test_publication_invokes_one_gateway_hop_and_settles_only_native_evidence(
    env, monkeypatch, stream, confirmed
):
    import json
    from decimal import Decimal

    from fastapi import Request
    from llm_billing_helpers import billing as setup_billing
    from test_desktop import bearer, native_client
    from test_llm_execution import GATEWAY, credentials, entries, upstream
    from test_mcp import listening

    from app.modules.model_gateway import billing

    admin = await env.client()
    bind(env, admin)
    await setup_billing(admin)
    app, state = upstream()
    request_id = uuid4().hex

    @app.middleware("http")
    async def correlate(request, call_next):
        response = await call_next(request)
        response.headers["X-Oneapi-Request-Id"] = request_id
        return response

    async with listening(app) as base:
        env.provider.settings.newapi_connections = [
            NewApiConnection(
                tenant_id=admin.tenant.id,
                base_url=base,
                management_token=SecretStr("management"),
                relay_key=SecretStr("relay-only"),
                relay_token_id=51,
            )
        ]
        env.provider.settings.llm_allowed_private_origins = [base]

        async def native(request, tenant_id, method, path, **kwargs):
            if path == "/api/channel/":
                return {"items": [channel(models="public", status=1)], "total": 1}
            if path == "/api/option/model_pricing":
                return {"entries": [{"model_name": "public", "effective": {"ModelRatio": 1}}]}
            if path == "/api/option/model_pricing/preflight":
                import time

                return {
                    "schema_version": 1,
                    "model": kwargs["payload"]["model"],
                    "group": "default",
                    "input_limit": kwargs["payload"]["input_limit"],
                    "output_limit": kwargs["payload"]["output_limit"],
                    "quota": "5000",
                    "quota_per_unit": "500000",
                    "pricing_version": "fixture",
                    "expression_hash": "fixture",
                    "expires_at": int(time.time()) + 60,
                }
            if path == "/api/status":
                return {"quota_per_unit": 500000}
            if path == "/api/log/":
                return {
                    "items": [
                        {
                            "id": 1,
                            "request_id": request_id,
                            "token_id": 51,
                            "model_name": "public",
                            "type": 2,
                            "quota": 1250,
                            "prompt_tokens": 100,
                            "completion_tokens": 10,
                            "other": json.dumps(
                                {
                                    "admin_info": {
                                        "usage_billing_path": "billing-usage-openai"
                                        if confirmed
                                        else "billing-usage-openai-estimated"
                                    }
                                }
                            ),
                        }
                    ]
                }
            raise AssertionError(path)

        monkeypatch.setattr(client, "call", native)
        body = {
            "model_name": "public",
            "name": "Public",
            "enabled": True,
            "audience": "organization",
            "context_window": 1000,
            "max_output": 100,
            "reserve_usd": "0.01",
            "capability_mode": "manual",
        }
        result = await admin.api.put(BASE + "/publication", json=body)
        assert result.status_code == 200, result.text
        published = result.json()["data"]
        assert (await admin.api.put(BASE + "/publication", json=body)).status_code == 409
        request = Request({"type": "http", "app": env.app})
        env.app.state.llm_outbox.reconcile = lambda record: billing.reconcile(request, record)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, published)
            response = await api.post(
                GATEWAY,
                headers=bearer(token),
                json={
                    "model": "public",
                    "messages": [{"role": "user", "content": "hi"}],
                    "stream": stream,
                },
            )
        assert response.status_code == 200 and '"error"' not in response.text, response.text
        assert len(state["calls"]) == 1 and state["calls"][0][0] == "v1"
        assert state["calls"][0][1]["model"] == "public"
        rows = await entries(admin)
        assert rows[0]["status"] == ("settled" if confirmed else "review")
        assert (
            Decimal(rows[0]["points"]) == Decimal("0.25")
            if confirmed
            else rows[0]["points"] is None
        )
        assert "management" not in response.text and "relay-only" not in response.text


@pytest.mark.parametrize(
    "change",
    [
        {"token_id": 99},
        {"model_name": "foreign"},
        {"request_id": "foreign"},
        {"quota": -1},
        {"quota": None},
        {"prompt_tokens": 0, "completion_tokens": 0},
        {"other": '{"admin_info":{"usage_billing_path":"local"}}'},
    ],
)
async def test_foreign_or_incomplete_native_bill_is_not_free(change):
    from app.modules.model_gateway.billing import verified_ledger

    attempt = {
        "upstream_id": "model",
        "gateway_request_id": "request",
        "gateway": {"token_id": 1, "quota_per_unit": 500000},
    }
    entry = {
        "id": 1,
        "token_id": 1,
        "request_id": "request",
        "model_name": "model",
        "type": 2,
        "quota": 0,
        "prompt_tokens": 10,
        "completion_tokens": 1,
        "other": '{"admin_info":{"usage_billing_path":"billing-usage-openai"}}',
    }
    assert verified_ledger(entry, attempt)["quota"] == 0
    assert verified_ledger(entry | change, attempt) is None


@pytest.mark.parametrize("usage_present", [True, False])
async def test_native_gateway_relay_and_ledger_contract(env, monkeypatch, usage_present):
    """Opt-in pinned New API relay; the supplier is a disposable local HTTP fixture."""
    import asyncio
    import json
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from fastapi import Request
    from llm_billing_helpers import billing as setup_billing
    from test_desktop import bearer, native_client
    from test_llm_execution import GATEWAY, credentials, entries

    token = os.getenv("ACTVERO_TEST_NEWAPI_TOKEN")
    base = os.getenv("ACTVERO_TEST_NEWAPI_URL")
    relay = os.getenv("ACTVERO_TEST_NEWAPI_RELAY")
    if not token or not relay or not base:
        pytest.skip("Explicit local New API contract credentials required")
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["content-length"]))))
            data = json.dumps(
                {
                    "id": "contract-response",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "contract-upstream",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": "local contract answer"},
                        }
                    ],
                    **(
                        {
                            "usage": {
                                "prompt_tokens": 100,
                                "completion_tokens": 10,
                                "total_tokens": 110,
                            }
                        }
                        if usage_present
                        else {}
                    ),
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    admin = await env.client()
    bind(env, admin)
    await setup_billing(admin)
    env.provider.settings.newapi_connections = [
        NewApiConnection(
            tenant_id=admin.tenant.id,
            base_url=base,
            management_token=SecretStr(token),
            relay_key=SecretStr(relay),
            relay_token_id=int(os.environ["ACTVERO_TEST_NEWAPI_RELAY_ID"]),
        )
    ]
    env.provider.settings.llm_allowed_private_origins = [base]
    name = "actvero-relay-contract-" + uuid4().hex[:10]
    request = Request({"type": "http", "app": env.app})
    channel_id = None
    try:
        result = await admin.api.post(
            BASE + "/channels",
            json={
                "name": name,
                "type": 43,
                "base_url": f"http://host.docker.internal:{server.server_port}",
                "key": "local-fixture-key",
                "models": [name],
                "model_mapping": {name: "deepseek-flash"},
            },
        )
        assert result.status_code == 200, result.text
        data = (await admin.api.get(BASE + "/channels", params={"q": name})).json()["data"]
        channel_id = next(c["id"] for c in data["items"] if c["name"] == name)
        snapshot = (await admin.api.get(BASE + "/prices", params={"model": name})).json()["data"]
        price = next(p for p in snapshot["entries"] if p["model_name"] == name)
        result = await admin.api.put(
            BASE + "/prices",
            json={
                "model_name": name,
                "expected_version": price["version"],
                "pricing": {
                    "ModelRatio": 1,
                    "CompletionRatio": 2,
                    "billing_setting.billing_mode": "ratio",
                },
            },
        )
        assert result.status_code == 200, result.text
        result = await admin.api.put(
            BASE + "/publication",
            json={
                "model_name": name,
                "name": name,
                "enabled": True,
                "audience": "administrators",
                "context_window": 1000,
                "max_output": 100,
                "reserve_usd": "0.01",
                "capability_mode": "auto",
            },
        )
        assert result.status_code == 200, result.text
        published = result.json()["data"]
        async with native_client(env) as api:
            _, bearer_token = await credentials(env, monkeypatch, api, admin, published)
            response = await api.post(
                GATEWAY,
                headers=bearer(bearer_token),
                json={
                    "model": name,
                    "messages": [
                        {
                            "role": "assistant",
                            "content": "prior answer",
                            "reasoning_content": "prior reasoning",
                        },
                        {"role": "user", "content": "local contract"},
                    ],
                    "reasoning_effort": "max" if usage_present else "none",
                    "max_completion_tokens": 100,
                },
            )
        assert response.status_code == 200, response.text
        assert response.json()["choices"][0]["message"]["content"] == "local contract answer"
        assert len(received) == 1 and received[0]["model"] == "deepseek-flash"
        assert received[0]["max_tokens"] == 100
        assert received[0]["messages"][0]["reasoning_content"] == "prior reasoning"
        assert (received[0].get("thinking") or {}).get("type") == (
            "enabled" if usage_present else "disabled"
        ), {
            k: received[0].get(k)
            for k in (
                "model",
                "reasoning_effort",
                "thinking",
                "max_tokens",
                "max_completion_tokens",
            )
        }
        if usage_present:
            assert received[0]["reasoning_effort"] == "max"
        for _ in range(25):
            rows = await entries(admin)
            if rows[0]["status"] != "reserved":
                break
            await asyncio.sleep(0.2)
        if usage_present:
            assert rows[0]["status"] == "settled", rows[0]
            assert rows[0]["points"] == "0.024", rows[0]
        else:
            assert rows[0]["status"] == "review", rows[0]
            assert rows[0]["points"] is None
            assert rows[0]["reserved_points"] != "0"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        if channel_id:
            assert (await admin.api.delete(BASE + f"/channels/{channel_id}")).status_code == 200
        snapshot = await client.call(
            request, admin.tenant.id, "GET", "/api/option/model_pricing", params={"model": name}
        )
        entry = next((p for p in snapshot.get("entries", []) if p["model_name"] == name), None)
        if entry:
            await client.call(
                request,
                admin.tenant.id,
                "PATCH",
                "/api/option/model_pricing",
                payload={
                    "changes": [
                        {"model_name": name, "expected_version": entry["version"], "reset": True}
                    ]
                },
            )


async def test_native_creation_keeps_provider_payload_and_restricts_operations(env, monkeypatch):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    bind(env, admin)
    native = AsyncMock(return_value=None)
    monkeypatch.setattr(client, "call", native)
    path = BASE + "/native/api/channel"
    body = {
        "mode": "multi_to_single",
        "multi_key_mode": "polling",
        "channel": {
            "name": "Native contract",
            "type": 33,
            "key": "aws:credential:format",
            "models": "alias",
            "group": "default",
            "status": 2,
            "setting": '{"region":"test-region","force_format":true}',
            "settings": '{"upstream_model_update_check":true}',
            "other": "native-provider-value",
            "model_mapping": '{"alias":"upstream"}',
        },
    }
    assert (await member.api.post(path, json=body)).status_code == 403
    assert (
        await admin.api.post(path, json=body, headers={"x-csrf-token": "wrong"})
    ).status_code == 403
    native.assert_not_awaited()
    result = await admin.api.post(path, json=body)
    assert result.status_code == 200, result.text
    assert native.await_args.kwargs["payload"] == body
    assert "aws:credential:format" not in result.text
    assert (await admin.api.get(BASE + "/native/api/user")).status_code == 404
    assert (await admin.api.get(BASE + "/native/api/channel/1/key")).status_code == 404
    assert (
        await admin.api.post(BASE + "/native/api/user/access_tokens", json={})
    ).status_code == 404


async def test_native_edit_round_trip_preserves_provider_fields_and_key(env, monkeypatch):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    bind(env, admin)
    row = channel(
        settings='{"aws_api_type":"mantle","unrecognized_native_setting":true}',
        header_override='{"x-native":"value"}',
        other="provider-specific",
        channel_info={"is_multi_key": True, "multi_key_size": 2, "multi_key_mode": "polling"},
    )
    writes = []

    async def native(request, tenant_id, method, path, **kwargs):
        assert tenant_id == admin.tenant.id
        assert path in {"/api/channel/4", "/api/channel/"}
        if method == "PUT":
            writes.append(deepcopy(kwargs["payload"]))
            row.update(kwargs["payload"])
            return channel(key="must-never-be-echoed")
        return deepcopy(row)

    monkeypatch.setattr(client, "call", native)
    detail = BASE + "/native/api/channel/4"
    path = BASE + "/native/api/channel/"
    assert (await member.api.get(detail)).status_code == 403
    result = await admin.api.get(detail)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    data = result.json()["data"]
    assert data["key"] == ""
    assert "supplier-secret" not in result.text
    assert data["settings"] == row["settings"]
    assert data["header_override"] == row["header_override"]
    assert data["channel_info"]["multi_key_mode"] == "polling"
    payload = {
        "id": 4,
        "name": "Edited native form",
        "key": "",
        "setting": row["setting"],
        "settings": row["settings"],
        "header_override": row["header_override"],
        "other": row["other"],
        "models": "public-model,another-model",
        "multi_key_mode": "random",
    }
    headers = {"If-Match": data["revision"]}
    assert (await member.api.put(path, json=payload, headers=headers)).status_code == 403
    assert (
        await admin.api.put(path, json=payload, headers=headers | {"x-csrf-token": "wrong"})
    ).status_code == 403
    assert not writes
    # A background connectivity test must not make an untouched editor stale.
    row.update(test_time=12345, response_time=350, balance=2.1, used_quota=12)
    saved = await admin.api.put(path, json=payload, headers=headers)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"success": True}
    assert writes == [{k: v for k, v in payload.items() if k != "key"}]
    assert row["key"] == "supplier-secret"
    assert row["status"] == 1
    assert (await admin.api.put(path, json=payload, headers=headers)).status_code == 409
    assert len(writes) == 1
    async with env.sessions() as db:
        events = list(await db.scalars(select(AuditEvent)))
        audit_text = repr([e.__dict__ for e in events])
        assert "supplier-secret" not in audit_text
        assert "provider-specific" not in audit_text


async def test_native_edit_requires_snapshot_and_rejects_status_or_invalid_id(env, monkeypatch):
    admin = await env.client()
    bind(env, admin)
    native = AsyncMock(return_value=channel())
    monkeypatch.setattr(client, "call", native)
    path = BASE + "/native/api/channel/"
    headers = {"If-Match": "a" * 64}
    for payload in ({"id": 0}, {"id": True}, {"id": "4"}, {"id": 4, "status": 2}):
        assert (await admin.api.put(path, json=payload, headers=headers)).status_code == 422
    assert (await admin.api.put(path, json={"id": 4})).status_code == 422
    native.assert_not_awaited()


async def test_channel_list_forwards_native_filters_and_pagination_without_credentials(
    env, monkeypatch
):
    admin = await env.client()
    bind(env, admin)
    native = AsyncMock(return_value={"items": [channel()], "total": 1})
    monkeypatch.setattr(client, "call", native)
    response = await admin.api.get(
        BASE + "/channels",
        params={
            "page": 2,
            "page_size": 50,
            "q": "Supplier",
            "model": "public-model",
            "state": "enabled",
            "type": 1,
            "group": "team",
            "sort_by": "response_time",
            "sort_order": "asc",
        },
    )
    assert response.status_code == 200, response.text
    assert native.await_args.args[3] == "/api/channel/search"
    assert native.await_args.kwargs["params"] == {
        "p": 2,
        "page_size": 50,
        "keyword": "Supplier",
        "model": "public-model",
        "status": "enabled",
        "type": 1,
        "group": "team",
        "sort_by": "response_time",
        "sort_order": "asc",
    }
    assert "supplier-secret" not in response.text
    assert response.json()["data"]["items"][0]["name"] == "Supplier"
    native.reset_mock()
    assert (await admin.api.get(BASE + "/channels?model=public-model")).status_code == 200
    assert native.await_args.args[3] == "/api/channel/search"
    native.reset_mock()
    for params in ({"sort_by": "key"}, {"state": "anything"}, {"page_size": 101}):
        assert (await admin.api.get(BASE + "/channels", params=params)).status_code == 422
    native.assert_not_awaited()


async def test_channel_quick_test_defers_model_to_native_and_preserves_test_options(
    env, monkeypatch
):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    bind(env, admin)
    native = AsyncMock(return_value={"time": 0.608})
    monkeypatch.setattr(client, "call", native)
    path = BASE + "/channels/4/test"
    assert (await member.api.post(path, json={})).status_code == 403
    assert (await admin.api.post(path, json={}, headers={"x-csrf-token": "bad"})).status_code == 403
    native.assert_not_awaited()
    response = await admin.api.post(path, json={})
    assert response.status_code == 200
    assert response.json()["data"]["time"] == 0.608
    assert native.await_args.args[2:4] == ("GET", "/api/channel/test/4")
    assert native.await_args.kwargs["params"] == {}
    response = await admin.api.post(
        path,
        json={
            "model": "chosen-model",
            "endpoint_type": "openai-response",
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert native.await_args.kwargs["params"] == {
        "model": "chosen-model",
        "endpoint_type": "openai-response",
        "stream": "true",
    }
    native.reset_mock()
    assert (await admin.api.post(path, json={"endpoint_type": "arbitrary"})).status_code == 422
    native.assert_not_awaited()


async def test_inline_routing_is_partial_and_model_replacement_requires_current_revision(
    env, monkeypatch
):
    admin = await env.client()
    bind(env, admin)
    row = channel()
    writes = []

    async def native(request, tenant_id, method, path, **kwargs):
        if method == "PUT":
            writes.append(deepcopy(kwargs["payload"]))
            row.update(kwargs["payload"])
            return None
        return deepcopy(row)

    monkeypatch.setattr(client, "call", native)
    path = BASE + "/channels/4/fields"
    response = await admin.api.patch(path, json={"priority": -3})
    assert response.status_code == 200, response.text
    assert writes == [{"id": 4, "priority": -3}]
    assert row["status"] == 1 and row["key"] == "supplier-secret"
    assert row["setting"] == '{"native_flag":true}'
    assert "supplier-secret" not in response.text
    assert (await admin.api.patch(path, json={"models": []})).status_code == 409
    assert (await admin.api.patch(path, json={"key": "not-allowed"})).status_code == 422
    revision = service.channel_view(row)["revision"]
    response = await admin.api.patch(path, json={"models": ["remaining"], "revision": revision})
    assert response.status_code == 200, response.text
    assert writes[-1] == {"id": 4, "models": "remaining"}
    assert (
        await admin.api.patch(path, json={"models": [], "revision": revision})
    ).status_code == 409
    assert len(writes) == 2
