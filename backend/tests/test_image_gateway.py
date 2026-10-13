"""Real SDK / loopback image admission, delivery, exact flat price and private logs."""

import asyncio
import json
from copy import deepcopy
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
from test_sdk_images import data_image

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.catalog_schemas import CatalogInput, ModelBinding, TokenPrice
from app.modules.llm.models import ModelCall, ModelChannel, UsageSettlement
from app.modules.llm.routing import fingerprint
from app.modules.llm.settlement import amount_for

pytestmark = pytest.mark.asyncio
env = identity_env
BASE = "/api/v1/llm/models/"
GATEWAY = "/api/llm/v1"
PRICE = {"currency": "USD", "metric": "images", "unit": 1, "input": "0.035"}


@pytest.fixture(autouse=True)
def identity(monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())


def upstream(reply=None):
    app, calls = FastAPI(), []

    @app.post("/v1/images/generations")
    async def images(request: Request):
        calls.append((dict(request.headers), await request.json()))
        return reply if reply is not None else {"created": 123, "data": [data_image()]}

    return app, calls


async def configure(admin, base, *, enabled=True, **extra):
    channel = await create_channel(
        admin, base_url=base + "/v1", models=[{"id": "opaque/model"}], declared_apis=["images"]
    )
    operation = {
        "kind": "image_generation",
        "enabled": enabled,
        "channel_id": channel["id"],
        "upstream_id": "opaque/model",
        "image": {"size": "1024x1024", "quality": "low", "max_prompt_characters": 100},
        "budget_price": PRICE,
        "bindings": [
            {
                "channel_id": channel["id"],
                "upstream_id": "opaque/model",
                "enabled": enabled,
                "price": {**PRICE, "input": "0.01"},
            }
        ],
    }
    response = await admin.api.post(
        BASE.rstrip("/"),
        json={
            "name": "团队图片",
            "slug": "team-image",
            "access": {"enabled": enabled, "audience": "organization"},
            "operations": [operation],
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_image_key_directory_sdk_exact_charge_idempotency_and_private_records(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        listed = await api.get(GATEWAY + "/models", headers=headers(key))
        assert listed.status_code == 200, listed.text
        directory = listed.json()["data"][0]
        assert directory["kind"] == "image_generation" and directory["output_modalities"] == [
            "image"
        ]
        assert directory["unit"] == 1 and directory["metric"] == "images"
        assert Decimal(directory["point_rates"]["input"]) == Decimal("3.5")
        assert "budget_price" not in json.dumps(directory) and "channel_id" not in json.dumps(
            directory
        )
        body = {"model": model["slug"], "prompt": "private-image-prompt"}
        result = await api.post(
            GATEWAY + "/images/generations",
            json=body,
            headers={**headers(key), "idempotency-key": "image-once"},
        )
        assert result.status_code == 200, result.text
        assert result.headers["cache-control"] == "no-store"
        assert result.json()["data"][0]["b64_json"] == data_image()["b64_json"]
        assert result.json()["usage"]["input_tokens"] is None  # SDK synthesized zero ignored.
        assert result.json()["usage"]["image_count"] == 1
        duplicate = await api.post(
            GATEWAY + "/images/generations",
            json=body,
            headers={**headers(key), "idempotency-key": "image-once"},
        )
        assert duplicate.status_code == 409 and len(calls) == 1
        assert calls[0][1] == {
            "model": "opaque/model",
            "prompt": body["prompt"],
            "n": 1,
            "size": "1024x1024",
            "quality": "low",
        }
        async with env.sessions() as db:
            log = await db.scalar(select(ModelCall))
            entry = await db.scalar(select(UsageSettlement))
            assert log.kind == "image_generation" and log.source == "access_key"
            assert entry.status == "settled" and entry.amount == Decimal("0.035")
            assert entry.reserved_amount == Decimal("0.035")
            assert Decimal(log.estimates["procurement"]["amount"]) == Decimal("0.01")
            raw = json.dumps([log.usage, log.attempts, entry.usage])
            assert body["prompt"] not in raw and data_image()["b64_json"] not in raw
        # Same shared identity can have chat too; history must use the actual call kind.
        history = (await admin.api.get("/api/v1/llm/settlements")).json()["items"][0]
        assert history["metric"] == "images" and history["kind"] == "image_generation"
        assert Decimal(history["points"]) == Decimal("3.5")


@pytest.mark.parametrize(
    "change",
    [
        {"n": 2},
        {"n": True},
        {"n": 1.0},
        {"size": "512x512"},
        {"quality": "high"},
        {"response_format": "url"},
        {"prompt": "x" * 101},
        {"prompt": " "},
        {"api_key": "injected"},
        {"stream": True},
    ],
)
async def test_image_rejects_unsupported_input_before_admission(env, change):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        await configure(admin, base)
        result = await api.post(
            GATEWAY + "/images/generations",
            json={"model": "team-image", "prompt": "hello", **change},
            headers=headers(key),
        )
        assert result.status_code == 422, result.text
        assert not calls
        async with env.sessions() as db:
            assert await db.scalar(select(UsageSettlement)) is None


async def test_image_draft_admin_test_does_not_publish_or_charge_member(env):
    admin, member = await env.client(), await env.client(role="member")
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base, enabled=False)
        body = {"model": model["slug"], "prompt": "draw"}
        assert (
            await api.post(GATEWAY + "/images/generations", json=body, headers=headers(key))
        ).status_code == 404
        assert (
            await member.api.post(BASE + model["id"] + "/test/images", json=body)
        ).status_code == 403
        assert (
            await admin.api.post(
                BASE + model["id"] + "/test/images", json=body, headers={"x-csrf-token": "bad"}
            )
        ).status_code == 403
        # A disabled binding is tested only by explicit selection, never by routing.
        binding = model["operations"][0]["bindings"][0]
        result = await admin.api.post(
            BASE + model["id"] + "/test/images",
            json=body,
            params={"channel_id": binding["channel_id"], "upstream_id": binding["upstream_id"]},
        )
        assert result.status_code == 200, result.text
        assert len(calls) == 1
        assert not (await admin.api.get(BASE + model["id"])).json()["access"]["enabled"]
        async with env.sessions() as db:
            assert await db.scalar(select(UsageSettlement)) is None


@pytest.mark.parametrize(
    "reply",
    [
        JSONResponse({"error": {"message": "secret-error"}}, status_code=429),
        {
            "data": [{"url": "https://127.0.0.1/private-secret"}],
            "usage": {"input_tokens": 5, "output_tokens": 7},
        },
        {"data": []},
    ],
)
async def test_image_ambiguous_failures_hold_and_manual_reconciliation(env, reply):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    app, calls = upstream(reply)
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        await configure(admin, base)
        result = await api.post(
            GATEWAY + "/images/generations",
            json={"model": "team-image", "prompt": "hi"},
            headers=headers(key),
        )
        assert result.status_code in (429, 502), result.text
        assert len(calls) == 1 and "secret" not in result.text
        entry = (await admin.api.get("/api/v1/llm/settlements")).json()["items"][0]
        assert entry["status"] == "review" and entry["points"] is None
        assert Decimal(entry["reserved_points"]) == Decimal("3.5")
        if isinstance(reply, dict) and reply.get("usage"):
            assert entry["usage"]["input_tokens"] == 5
        resolved = await admin.api.post(
            "/api/v1/llm/settlements/" + entry["id"] + "/reconcile",
            json={
                "version": entry["version"],
                "action": "settle",
                "usage": {"input": 1},
                "reason": "上游账单确认一张",
            },
        )
        assert resolved.status_code == 200, resolved.text
        assert Decimal(resolved.json()["items"][0]["points"]) == Decimal("3.5")


async def test_image_budget_exhaustion_and_current_permission(env):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin, points="3.5")
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        body = {"model": model["slug"], "prompt": "hello"}
        results = await asyncio.gather(
            *[
                api.post(GATEWAY + "/images/generations", json=body, headers=headers(key))
                for _ in range(2)
            ]
        )
        assert sorted(r.status_code for r in results) == [200, 429]
        assert len(calls) == 1
        await update(admin, model, access={**model["access"], "audience": "administrators"})
        assert (
            await api.post(GATEWAY + "/images/generations", json=body, headers=headers(key))
        ).status_code == 404
        assert not (await api.get(GATEWAY + "/models", headers=headers(key))).json()["data"]


async def test_image_price_validation_and_exact_units():
    price = TokenPrice.model_validate(PRICE)
    assert price.unit == 1 and amount_for(price, {"image_count": 3}) == Decimal("0.105")
    assert amount_for(price, {"input_tokens": 0, "output_tokens": 0}) is None
    for changed in [{"unit": 1000000}, {"output": "0"}, {"input": 0.1}]:
        with pytest.raises(ValueError):
            TokenPrice.model_validate({**PRICE, **changed})
    config = {"name": "image", "slug": "image", "operations": [{"kind": "image_generation"}]}
    assert CatalogInput.model_validate(config).operation_configs()[0].enabled is False
    invalid = deepcopy(config)
    invalid["operations"][0]["budget_price"] = {"currency": "USD", "input": "1"}
    with pytest.raises(ValueError):
        CatalogInput.model_validate(invalid)


async def test_image_extension_preserves_persisted_route_fingerprints():
    channel = ModelChannel(
        id=UUID(int=1),
        base_url="https://example.test/v1",
        auth_mode="none",
        sealed_key=None,
        version=1,
    )
    binding = ModelBinding(channel_id=channel.id, upstream_id="model")
    # Frozen pre-image hash format: existing routes must retain their test evidence.
    prior = {
        "chat": "06f6ee44cccf44472694c29cc293871f501b2a0f3cae79cedf3624f0da5c84f3",
        "embedding": "0abd07a69b667318bccdde70e4032d3983c4909e677de27769795d4670772749",
        "rerank": "cedccc8136f55b157ef771339d94b7729c9ab498e3966d12903c5cfd7024a3e8",
    }
    for kind, expected in prior.items():
        config = CatalogInput.model_validate({"name": "model", "slug": "model", "kind": kind})
        assert fingerprint(config, binding, channel) == expected
    config = CatalogInput(name="model", slug="model", kind="image_generation")
    before = fingerprint(config, binding, channel)
    config.image.quality = "high"
    assert fingerprint(config, binding, channel) != before


async def test_image_desktop_shares_key_budget_and_scope(env, monkeypatch):
    admin, member = await env.client(), await env.client(role="member")
    await billing(admin, points="3.5")
    key, _ = await create_key(member)
    app, calls = upstream()
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        root, token = await credentials(env, monkeypatch, api, member, model)
        body = {"model": model["slug"], "prompt": "hello"}
        assert (
            await api.post(GATEWAY + "/images/generations", json=body, headers=bearer(root))
        ).status_code == 401
        result = await api.post(GATEWAY + "/images/generations", json=body, headers=bearer(token))
        assert result.status_code == 200, result.text
        assert (
            await api.post(GATEWAY + "/images/generations", json=body, headers=headers(key))
        ).status_code == 429
        assert len(calls) == 1
        mine = await api.get("/api/v1/desktop/llm/usage", headers=bearer(root))
        assert mine.status_code == 200, mine.text
        assert "procurement" not in mine.text and "USD" not in mine.text
        async with env.sessions() as db:
            log = await db.scalar(select(ModelCall))
            assert log.source == "desktop" and log.device_id is not None


@pytest.mark.parametrize("cancel", [False, True])
async def test_image_revocation_and_cancellation_during_delivery(env, monkeypatch, cancel):
    from app.modules.llm import sdk_execution as runtime

    admin, member = await env.client(), await env.client(role="member")
    await billing(admin)
    key, _ = await create_key(member)
    entered, release = asyncio.Event(), asyncio.Event()
    delivery = runtime.deliver_image

    async def slow_delivery(*args):
        entered.set()
        await release.wait()
        return await delivery(*args)

    monkeypatch.setattr(runtime, "deliver_image", slow_delivery)
    app, calls = upstream(
        {"data": [data_image()], "usage": {"input_tokens": 5, "output_tokens": 7}}
    )
    async with listening(app) as base, native_client(env) as api:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure(admin, base)
        pending = asyncio.create_task(
            api.post(
                GATEWAY + "/images/generations",
                json={"model": model["slug"], "prompt": "hi"},
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
            result = await pending
            assert result.status_code == 404 and "b64_json" not in result.text
        assert len(calls) == 1
        async with env.sessions() as db:
            entry = await db.scalar(select(UsageSettlement))
            log = await db.scalar(select(ModelCall))
            assert entry.usage["input_tokens"] == log.usage["input_tokens"] == 5
            assert entry.status == ("review" if cancel else "settled")
            if cancel:
                assert entry.amount is None and entry.reserved_amount == Decimal("0.035")
                assert log.attempts[0]["usage"]["output_tokens"] == 7
                assert log.termination_code == "caller_cancelled"
            else:
                assert entry.amount == Decimal(
                    "0.035"
                )  # Actual generation occurred before revocation.
