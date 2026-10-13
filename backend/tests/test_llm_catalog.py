"""Catalog configuration and exact draft prices against isolated PostgreSQL."""

import asyncio
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel

from app.modules.audit.models import AuditEvent
from app.modules.llm.models import CatalogModel
from app.modules.members.models import Membership

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm/models"
ESTIMATE = "/api/v1/llm/prices/estimate"
CONFIG = {"name": "统一模型", "slug": "team-chat"}
PRICE = {
    "currency": "USD",
    "unit": 1000,
    "input": "0.002",
    "output": "0.008",
    "cache_read": "0.0002",
}


async def create(admin, **extra):
    result = await admin.api.post(BASE, json=CONFIG | extra)
    assert result.status_code == 200, result.text
    return result.json()


async def test_catalog_permissions_and_private_prices(env):
    admin = await env.client()
    row = await create(admin, budget_price=PRICE)
    path = BASE + "/" + row["id"]
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    for caller in (member, outsider):
        for method, url, body in [
            ("GET", BASE, None),
            ("GET", path, None),
            ("POST", BASE, CONFIG),
            ("PUT", path, CONFIG | {"version": 1}),
            ("PUT", path + "/archive", {"version": 1, "archived": True}),
            ("POST", ESTIMATE, {"price": PRICE, "usage": {"input": 100}}),
        ]:
            response = await caller.api.request(method, url, json=body)
            assert response.status_code == 403
            assert "budget_price" not in response.text
    assert (
        await admin.api.post(BASE, json=CONFIG, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    assert (
        await admin.api.post(
            ESTIMATE, json={"price": PRICE, "usage": {}}, headers={"origin": "https://other.test"}
        )
    ).status_code == 403
    assert (await admin.api.get(BASE + "/" + str(uuid4()))).status_code == 404
    async with env.sessions() as db:
        membership = await db.get(Membership, admin.member.id)
        membership.role = "member"
        await db.commit()
    assert (await admin.api.put(path, json=CONFIG | {"version": 1})).status_code == 403
    admin.api.cookies.clear()
    assert (await admin.api.get(BASE)).status_code == 401
    assert (
        await admin.api.get(path, headers={"authorization": "Bearer desktop-test"})
    ).status_code == 401


async def test_atomic_config_prices_and_channel_state(env):
    admin = await env.client()
    channel = await create_channel(admin, models=[{"id": "upstream-a"}])
    binding = {
        "channel_id": channel["id"],
        "upstream_id": "upstream-a",
        "price": PRICE | {"currency": "CNY"},
    }
    row = await create(
        admin,
        bindings=[binding],
        budget_price=PRICE,
        context_window=32000,
        max_output=8000,
        capabilities={"tools": "supported"},
    )
    path = BASE + "/" + row["id"]
    assert row["budget_price"]["unit"] == 1000000
    assert Decimal(row["budget_price"]["input"]) == 2
    assert row["bindings"][0]["price"]["currency"] == "CNY"
    assert row["capabilities"]["streaming"] == "unknown"
    assert row["binding_states"][0]["state"] == "registered"
    assert "test-secret" not in str(row) and "base_url" not in str(row)
    assert (await admin.api.get(BASE + "?q=team")).json()["total"] == 1
    bad = CONFIG | {
        "version": 1,
        "name": "不应保存",
        "bindings": [binding | {"channel_id": str(uuid4())}],
        "budget_price": PRICE,
    }
    assert (await admin.api.put(path, json=bad)).status_code == 422
    fresh = (await admin.api.get(path)).json()
    assert fresh["name"] == CONFIG["name"] and fresh["version"] == 1
    assert (
        await admin.api.post(
            BASE, json=CONFIG | {"slug": "different", "bindings": [binding, binding]}
        )
    ).status_code == 422
    assert (
        await admin.api.post(
            BASE,
            json=CONFIG
            | {"slug": "different", "bindings": [binding | {"upstream_id": "not-registered"}]},
        )
    ).status_code == 422
    channel_path = "/api/v1/llm/channels/" + channel["id"]
    await admin.api.put(channel_path + "/archive", json={"version": 1, "archived": True})
    assert (await admin.api.get(path)).json()["binding_states"][0]["state"] == "archived"
    assert (
        await admin.api.post(BASE, json=CONFIG | {"slug": "another", "bindings": [binding]})
    ).status_code == 422
    # Existing mapping remains editable and visibly stale, never silently removed.
    updated = await admin.api.put(
        path, json=CONFIG | {"version": 1, "bindings": [binding], "budget_price": PRICE}
    )
    assert updated.status_code == 200 and len(updated.json()["bindings"]) == 1
    await admin.api.put(channel_path + "/archive", json={"version": 2, "archived": False})
    await admin.api.request(
        "DELETE", channel_path + "/models", json={"version": 3, "models": [{"id": "upstream-a"}]}
    )
    assert (await admin.api.get(path)).json()["binding_states"][0]["state"] == "missing"
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CatalogModel)) == 1
        actions = (
            await db.scalars(select(AuditEvent.action).where(AuditEvent.action.like("llm.model.%")))
        ).all()
        assert actions == ["llm.model.create", "llm.model.update"]


async def test_conflicts_archive_restore_and_pagination(env):
    admin = await env.client()
    row = await create(admin)
    path = BASE + "/" + row["id"]
    results = await asyncio.gather(
        *[admin.api.put(path, json=CONFIG | {"version": 1, "name": str(i)}) for i in range(2)]
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    assert (await admin.api.post(BASE, json=CONFIG)).status_code == 409
    assert (
        await admin.api.put(path + "/archive", json={"version": 2, "archived": True})
    ).status_code == 200
    assert (await admin.api.get(BASE)).json()["total"] == 0
    assert (await admin.api.get(BASE + "?state=archived")).json()["total"] == 1
    assert (await admin.api.put(path, json=CONFIG | {"version": 3})).status_code == 409
    assert (await admin.api.post(BASE, json=CONFIG)).status_code == 409
    assert (
        await admin.api.put(path + "/archive", json={"version": 3, "archived": False})
    ).status_code == 200
    for i in range(21):
        await create(admin, slug=f"model-{i}")
    first = (await admin.api.get(BASE)).json()
    second = (await admin.api.get(BASE + "?page=2")).json()
    assert first["total"] == 22 and len(first["items"]) == 20 and len(second["items"]) == 2
    assert not {m["id"] for m in first["items"]} & {m["id"] for m in second["items"]}


async def test_exact_price_units_estimate_and_unknown_rates(env):
    admin = await env.client()
    row = await create(admin, budget_price=PRICE)
    body = {
        "price": row["budget_price"],
        "usage": {"input": 4000, "output": 2000, "cache_read": 5000},
    }
    response = await admin.api.post(ESTIMATE, json=body)
    assert response.status_code == 200, response.text
    assert Decimal(response.json()["total"]) == Decimal("0.025")
    small = PRICE | {"input": "0.000000000000001"}
    response = await admin.api.post(ESTIMATE, json={"price": small, "usage": {"input": 1}})
    assert Decimal(response.json()["total"]) == Decimal("0.000000000000000001")
    for unit, value in [(1000, "0.002"), (1000000, "2")]:
        response = await admin.api.post(
            ESTIMATE,
            json={"price": PRICE | {"unit": unit, "input": value}, "usage": {"input": 1234567}},
        )
        assert Decimal(response.json()["total"]) == Decimal("2.469134")
    assert (
        await admin.api.post(ESTIMATE, json=body | {"usage": {"cache_write_5m": 1}})
    ).status_code == 422
    response = await admin.api.post(
        ESTIMATE, json={"price": PRICE | {"cache_write_5m": "0"}, "usage": {"cache_write_5m": 1000}}
    )
    assert response.status_code == 200 and Decimal(response.json()["total"]) == 0
    # Estimates neither save a model nor create a ledger/audit write.
    async with env.sessions() as db:
        assert await db.scalar(select(func.count()).select_from(CatalogModel)) == 1
        saved = await db.get(CatalogModel, UUID(row["id"]))
        assert saved.version == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"context_window": 100, "max_output": 101},
        {"context_window": 0},
        {"slug": "invalid slug"},
        {"budget_price": PRICE | {"input": "-1"}},
        {"budget_price": PRICE | {"input": "NaN"}},
        {"budget_price": PRICE | {"input": 0.002}},
        {"budget_price": PRICE | {"currency": ""}},
        {"budget_price": PRICE | {"unit": 100}},
        {"budget_price": PRICE | {"input": "1000001"}},
        {"budget_price": PRICE | {"input": "0.0000000000000001"}},
        {"budget_price": PRICE | {"unit": 1000000, "input": "0.000000000000001"}},
    ],
)
async def test_invalid_configuration_is_rejected_without_writes(env, extra):
    admin = await env.client()
    assert (await admin.api.post(BASE, json=CONFIG | extra)).status_code == 422
    assert (await admin.api.get(BASE)).json()["total"] == 0
