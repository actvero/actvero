"""Deployment-wide gateway connection keeps ownership derived from Actvero actors."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from fastapi import HTTPException, Request
from pydantic import ValidationError
from test_identity_access import env as identity_env

from app.core.config import Settings
from app.modules.model_gateway import client, execution
from app.modules.model_gateway.config import NewApiGateway
from app.modules.model_gateway.publication import origin_hash

env = identity_env
pytestmark = pytest.mark.asyncio


def reply(data, code=200):
    return httpx2.Response(code, json={"success": code == 200, "data": data})


async def test_shared_connection_requires_one_format_and_both_credentials(monkeypatch):
    monkeypatch.delenv("ACTVERO_NEWAPI_CONNECTIONS", raising=False)
    settings = Settings(
        _env_file=None, newapi_base_url="https://gateway.example/", newapi_management_token="secret"
    )
    assert settings.newapi_gateway.base_url == "https://gateway.example"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, newapi_base_url="https://gateway.example")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            newapi_gateway={"base_url": "https://gateway.example", "management_token": "secret"},
            newapi_connections=[
                {"tenant_id": uuid4(), "base_url": "https://other.example", "management_token": "s"}
            ],
        )


async def test_bridge_owner_and_credentials_are_server_derived(env, monkeypatch):
    env.provider.settings.newapi_gateway = NewApiGateway(
        base_url="https://gateway.example", management_token="private-management"
    )
    first, second = uuid4(), uuid4()
    sent = []

    async def native(request, config, method, path, **kwargs):
        sent.append((config.tenant_id, method, path, kwargs))
        if path.endswith("/connect"):
            return reply(
                {
                    "schema_version": 1,
                    "namespace": "avt_" + config.tenant_id.hex + "__",
                    "relay_key": config.tenant_id.hex + "fixture",
                    "relay_token_id": 7 if config.tenant_id == first else 8,
                    "relay_group": "default",
                }
            )
        return reply({"items": [], "total": 0})

    monkeypatch.setattr(client, "_send", native)
    request = Request({"type": "http", "app": env.app})
    for owner in (first, first, second):
        await client.call(
            request,
            owner,
            "POST",
            "/api/channel/",
            payload={"organization": str(second), "channel": {"name": "same"}},
        )
    assert sum(path.endswith("/connect") for _, _, path, _ in sent) == 2
    assert {path for _, _, path, _ in sent if path.endswith("/bridge")} == {
        f"/api/actvero/organizations/{first}/bridge",
        f"/api/actvero/organizations/{second}/bridge",
    }
    a, b = client.connection(request, first), client.connection(request, second)
    assert a.relay_key != b.relay_key
    assert client.connection_id(a) != client.connection_id(b)
    assert a.namespace != b.namespace


async def test_bridge_rejects_wrong_owner_handshake_without_dispatch(env, monkeypatch):
    env.provider.settings.newapi_gateway = NewApiGateway(
        base_url="https://gateway.example", management_token="private-management"
    )
    send = AsyncMock(return_value=reply({"schema_version": 1, "namespace": "foreign"}))
    monkeypatch.setattr(client, "_send", send)
    request = Request({"type": "http", "app": env.app})
    with pytest.raises(HTTPException) as error:
        await client.call(request, uuid4(), "GET", "/api/channel/")
    assert error.value.status_code == 502
    assert send.await_count == 1
    assert "private-management" not in str(error.value.detail)


async def test_execution_qualifies_only_native_hop_and_billing_evidence(env, monkeypatch):
    owner = uuid4()
    env.provider.settings.newapi_gateway = NewApiGateway(
        base_url="https://gateway.example", management_token="management"
    )
    connection = client.connection(Request({"type": "http", "app": env.app}), owner)
    from pydantic import SecretStr

    connection = connection.model_copy(
        update={"relay_key": SecretStr("relay"), "relay_token_id": 7}
    )
    monkeypatch.setattr(client, "relay_connection", AsyncMock(return_value=connection))
    monkeypatch.setattr(client, "call", AsyncMock(return_value={"quota_per_unit": 500000}))
    candidate = SimpleNamespace(
        model="same-model",
        base="https://gateway.example/v1",
        payload={"model": "same-model"},
        evidence={"upstream_id": "same-model"},
    )
    config = SimpleNamespace(
        gateway=SimpleNamespace(origin_hash=origin_hash(connection.base_url)),
        kind="chat",
        routing=SimpleNamespace(mode="fixed", fallback=False),
    )
    await execution.prepare(Request({"type": "http", "app": env.app}), owner, config, [candidate])
    assert candidate.model == "avt_" + owner.hex + "__same-model"
    assert candidate.payload["model"] == candidate.evidence["upstream_id"] == candidate.model
    assert candidate.evidence["gateway"]["token_id"] == 7
    assert candidate.key == "relay"
    assert candidate.protect is False


async def test_platform_operator_reference_cannot_use_gateway_credentials(env, monkeypatch):
    from sqlalchemy import select

    from app.modules.auth.models import WebSession
    from app.modules.members.models import Membership
    from app.modules.tenants.models import PlatformOperator

    admin = await env.client()
    operator = await env.client(role="member", tenant=admin.tenant)
    env.provider.settings.platform_edition = "saas"
    async with env.sessions() as db:
        db.add(PlatformOperator(user_id=operator.user.id))
        session = await db.get(WebSession, operator.session.id)
        session.tenant_id = admin.tenant.id
        member = await db.scalar(select(Membership).where(Membership.id == operator.member.id))
        member.source = "platform"
        await db.commit()
    call = AsyncMock()
    monkeypatch.setattr(client, "call", call)
    for path in ("/api/v1/model-gateway/channels", "/api/v1/model-gateway/native/api/models/"):
        assert (await operator.api.get(path)).status_code == 403
    call.assert_not_awaited()


async def test_two_organizations_through_real_native_bridge(env):
    import os

    from sqlalchemy import text

    from app.modules.auth.models import WebSession
    from app.modules.tenants.models import Tenant

    base = os.getenv("ACTVERO_TEST_SHARED_NEWAPI_URL")
    token = os.getenv("ACTVERO_TEST_SHARED_NEWAPI_TOKEN")
    if not base or not token:
        pytest.skip("Isolated native organization gateway required")
    env.provider.settings.platform_edition = "saas"
    env.provider.settings.newapi_gateway = NewApiGateway(base_url=base, management_token=token)
    env.provider.settings.llm_allowed_private_origins = [base]
    async with env.sessions() as db:
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        other = Tenant(name="Other organization")
        db.add(other)
        await db.commit()
    first = await env.client()
    # The fixture selected its first tenant above; create another isolated owner explicitly.
    async with env.sessions() as db:
        distinct = Tenant(name="Independent organization")
        db.add(distinct)
        await db.commit()
    second = await env.client(tenant=distinct)
    async with env.sessions() as db:
        for actor in (first, second):
            session = await db.get(WebSession, actor.session.id)
            session.tenant_id = actor.tenant.id
        await db.commit()
    ids = {}
    for actor in (first, second):
        response = await actor.api.post(
            "/api/v1/model-gateway/native/api/channel",
            json={
                "mode": "single",
                "channel": {
                    "name": "same",
                    "type": 1,
                    "key": "fixture-key",
                    "group": "default",
                    "models": "same-model",
                    "model_mapping": "{}",
                    "base_url": "https://example.com",
                },
            },
        )
        assert response.status_code == 200, response.text
        response = await actor.api.get("/api/v1/model-gateway/channels")
        assert response.status_code == 200, response.text
        page = response.json()["data"]
        assert page["total"] == 1
        ids[actor.user.id] = page["items"][0]["id"]
        assert page["items"][0]["name"] == "same"
        response = await actor.api.post(
            "/api/v1/model-gateway/native/api/models/",
            json={"model_name": "same-model", "status": 1, "sync_official": 0},
        )
        assert response.status_code == 200, response.text
    for actor, foreign in ((first, second), (second, first)):
        response = await actor.api.get(
            f"/api/v1/model-gateway/native/api/channel/{ids[foreign.user.id]}"
        )
        assert response.status_code == 404, response.text
        response = await actor.api.get("/api/v1/model-gateway/native/api/models/")
        assert response.status_code == 200, response.text
        assert response.json()["data"]["total"] == 1


async def test_legacy_connection_refuses_an_organization_gateway(env, monkeypatch):
    from app.modules.model_gateway.config import NewApiConnection

    owner = uuid4()
    env.provider.settings.newapi_connections = [
        NewApiConnection(
            tenant_id=owner, base_url="https://gateway.example", management_token="legacy"
        )
    ]
    send = AsyncMock(return_value=reply({"actvero_organization_isolation": True}))
    monkeypatch.setattr(client, "_send", send)
    with pytest.raises(HTTPException) as error:
        await client.call(
            Request({"type": "http", "app": env.app}), owner, "DELETE", "/api/channel/1"
        )
    assert error.value.status_code == 409
    assert send.await_count == 1
    assert send.await_args.args[2:] == ("GET", "/api/status")
