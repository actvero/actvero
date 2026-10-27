"""Native model UI contracts, authorized through the active organization."""

from copy import deepcopy
from unittest.mock import AsyncMock

import httpx2
import pytest
from test_identity_access import env as identity_env
from test_model_gateway import bind

from app.modules.model_gateway import client

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/model-gateway/native"


def model(**changes):
    return {
        "id": 21,
        "model_name": "independent-model",
        "description": "Description",
        "icon": "",
        "tags": "reasoning",
        "vendor_id": 0,
        "endpoints": "",
        "status": 1,
        "sync_official": 0,
        "name_rule": 0,
        "created_time": 100,
        "updated_time": 100,
        "bound_channels": [],
        "enable_groups": [],
        "configured_channel_count": 0,
        "has_metadata": True,
        "square_state": "unavailable",
        "key": "never-return-this",
        **changes,
    }


async def test_native_model_listing_preserves_filters_counts_and_repeated_prices(env, monkeypatch):
    admin = await env.client()
    bind(env, admin)
    calls = []

    async def native(request, tenant_id, method, path, **kwargs):
        assert tenant_id == admin.tenant.id
        calls.append((method, path, kwargs))
        if path == "/api/models/search":
            return {
                "items": [model()],
                "total": 1,
                "vendor_counts": {"all": 1},
                "page": 2,
                "page_size": 10,
            }
        return {"entries": [], "options": {"quota_per_unit": 500000}, "empty_version": "empty"}

    monkeypatch.setattr(client, "call", native)
    response = await admin.api.get(
        BASE + "/api/models/search",
        params={
            "p": 2,
            "page_size": 10,
            "keyword": "independent",
            "vendor": "7",
            "status": "enabled",
            "square_state": "unavailable",
            "sync_official": "no",
            "include_channel_models": "true",
            "ignored": "not-forwarded",
        },
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["data"]["vendor_counts"] == {"all": 1}
    assert response.json()["data"]["items"][0]["configured_channel_count"] == 0
    assert "never-return-this" not in response.text
    assert dict(calls[0][2]["params"]) == {
        "p": "2",
        "page_size": "10",
        "keyword": "independent",
        "vendor": "7",
        "status": "enabled",
        "square_state": "unavailable",
        "sync_official": "no",
        "include_channel_models": "true",
    }
    await admin.api.get(
        BASE + "/api/option/model_pricing", params=[("model", "first"), ("model", "second")]
    )
    assert calls[-1][2]["params"] == {"model": ["first", "second"]}
    assert (
        await admin.api.get(BASE + "/api/models", params={"page_size": 1001})
    ).status_code == 422


async def test_native_model_create_update_status_and_conflict(env, monkeypatch):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    bind(env, admin)
    row = model()
    writes = []

    async def native(request, tenant_id, method, path, **kwargs):
        assert tenant_id == admin.tenant.id
        if method == "GET":
            return deepcopy(row)
        writes.append((method, path, deepcopy(kwargs)))
        row.update(kwargs["payload"])
        return deepcopy(row)

    monkeypatch.setattr(client, "call", native)
    payload = {
        key: row[key]
        for key in (
            "model_name",
            "description",
            "icon",
            "tags",
            "vendor_id",
            "endpoints",
            "status",
            "sync_official",
            "name_rule",
        )
    } | {"enable_groups": [], "quota_types": []}
    path = BASE + "/api/models/"
    assert (await member.api.post(path, json=payload)).status_code == 403
    assert (
        await admin.api.post(path, json=payload, headers={"x-csrf-token": "wrong"})
    ).status_code == 403
    assert not writes
    created = await admin.api.post(path, json=payload)
    assert created.status_code == 200, created.text
    assert writes[-1][2]["payload"] == payload
    assert "channel_id" not in writes[-1][2]["payload"]
    assert "never-return-this" not in created.text
    detail = (await admin.api.get(BASE + "/api/models/21")).json()["data"]
    changed = payload | {"id": 21, "description": "New description", "sync_official": 1}
    headers = {"If-Match": detail["revision"]}
    assert (await admin.api.put(path, json=changed)).status_code == 409
    saved = await admin.api.put(path, json=changed, headers=headers)
    assert saved.status_code == 200, saved.text
    assert writes[-1][2]["payload"] == changed
    assert (await admin.api.put(path, json=changed, headers=headers)).status_code == 409
    count = len(writes)
    assert (
        await admin.api.put(path + "?status_only=true", json={"id": 21, "status": 0})
    ).status_code == 200
    assert writes[-1][2]["params"] == {"status_only": "true"}
    assert len(writes) == count + 1
    assert (
        await admin.api.put(
            path + "?status_only=true",
            json={"id": 21, "status": 1, "model_name": "must-not-change"},
        )
    ).status_code == 422


async def test_native_sync_prices_and_vendor_versions_are_forwarded_without_broad_proxy(
    env, monkeypatch
):
    admin = await env.client()
    bind(env, admin)
    call = AsyncMock(return_value={"version": "native-result"})
    monkeypatch.setattr(client, "call", call)
    operations = [
        (
            "post",
            "/api/models/sync_upstream",
            {
                "source_version": "source",
                "locale": "zh",
                "source": "official",
                "selections": [
                    {
                        "model_name": "new-model",
                        "record_version": "record",
                        "create": True,
                        "fields": [],
                    }
                ],
            },
        ),
        (
            "patch",
            "/api/option/model_pricing",
            {
                "changes": [
                    {
                        "model_name": "new-model",
                        "expected_version": "price-version",
                        "pricing": {"ModelRatio": 0, "CompletionRatio": 0},
                    }
                ],
            },
        ),
        (
            "post",
            "/api/vendors/operations/preview",
            {"action": "assign", "model_ids": [21], "target_vendor_id": 3},
        ),
        (
            "post",
            "/api/vendors/operations",
            {
                "action": "assign",
                "model_ids": [21],
                "target_vendor_id": 3,
                "expected_version": "vendor-version",
            },
        ),
        (
            "post",
            "/api/prefill_group",
            {"type": "model", "name": "Native group", "items": ["one", "two"]},
        ),
    ]
    for method, path, payload in operations:
        response = await getattr(admin.api, method)(BASE + path, json=payload)
        assert response.status_code == 200, response.text
        assert call.await_args.kwargs["payload"] == payload
    count = call.await_count
    for path in (
        "/api/option/",
        "/api/user/self",
        "/api/deployments/settings",
        "/api/channel/1/key",
    ):
        assert (await admin.api.get(BASE + path)).status_code == 404
    for path in ("/api/option/", "/api/user/access_tokens", "/api/deployments/"):
        assert (await admin.api.post(BASE + path, json={})).status_code == 404
    assert call.await_count == count


async def test_native_public_pricing_preserves_top_level_contract_without_unknown_fields(
    env, monkeypatch
):
    admin = await env.client()
    bind(env, admin)
    packet = {
        "success": True,
        "data": [{"model_name": "one", "quota_type": 0}],
        "vendors": [],
        "group_ratio": {"default": 1},
        "usable_group": {},
        "supported_endpoint": {"openai": "/v1/chat/completions"},
        "auto_groups": [],
        "key": "must-not-return",
    }
    send = AsyncMock(return_value=httpx2.Response(200, json=packet))
    monkeypatch.setattr(client, "send", send)
    response = await admin.api.get(BASE + "/api/pricing")
    assert response.status_code == 200
    assert response.json()["group_ratio"] == {"default": 1}
    assert response.json()["data"] == packet["data"]
    assert "must-not-return" not in response.text
