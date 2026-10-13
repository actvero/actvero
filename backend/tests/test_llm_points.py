import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model

from app.modules.llm.models import PointConversion
from app.modules.llm.points import current_conversion

env = identity_env
pytestmark = pytest.mark.asyncio
BASE = "/api/v1/llm"
PRICE = {"currency": "USD", "unit": 1000000, "input": "2", "output": "8", "cache_read": "0.2"}


async def configure(admin, **changes):
    response = await admin.api.put(
        BASE + "/point-conversion",
        json={
            "currency": "USD",
            "points_per_currency": "100",
            "version": 0,
        }
        | changes,
    )
    assert response.status_code == 200, response.text
    return response.json()["conversion"]


async def test_model_prices_and_usage_convert_exactly_and_procurement_is_separate(env):
    admin = await env.client()
    model = await create_model(admin, budget_price=PRICE)
    assert model["point_price"]["status"] == "unconfigured"
    assert (await admin.api.get(BASE + "/point-conversion")).json()["conversion"] is None
    conversion = await configure(admin)
    model = (await admin.api.get(BASE + "/models/" + model["id"])).json()
    price = model["point_price"]
    assert price["status"] == "ready" and price["conversion"] == conversion
    assert price["rates"] == {
        "input": "200",
        "output": "800",
        "cache_read": "20",
        "cache_write_5m": None,
        "cache_write_1h": None,
    }
    listed = (await admin.api.get(BASE + "/models")).json()["items"][0]
    assert listed["point_price"] == price
    body = {
        "price": PRICE,
        "usage": {"input": 1000, "output": 500, "cache_read": 2000},
        "include_points": True,
    }
    result = (await admin.api.post(BASE + "/prices/estimate", json=body)).json()
    assert Decimal(result["total"]) == Decimal("0.0064")
    assert result["points"]["total"] == "0.64"
    assert result["points"]["conversion"]["version"] == 1
    ordinary = (
        await admin.api.post(BASE + "/prices/estimate", json=body | {"include_points": False})
    ).json()
    assert ordinary["points"] is None
    for metric in ("characters", "search_units"):
        result = await admin.api.post(
            BASE + "/prices/estimate",
            json={
                "price": {"currency": "USD", "metric": metric, "unit": 1000, "input": "0.002"},
                "usage": {"input": 1000},
                "include_points": True,
            },
        )
        assert result.status_code == 200
        assert result.json()["points"]["total"] == "0.2"
        assert result.json()["points"]["metric"] == metric


async def test_missing_currency_mismatch_unknown_and_zero_remain_distinct(env):
    admin = await env.client()
    body = {"price": PRICE, "usage": {"input": 1}, "include_points": True}
    result = (await admin.api.post(BASE + "/prices/estimate", json=body)).json()
    assert result["points"]["status"] == "unconfigured" and result["points"]["total"] is None
    await configure(admin, currency="CNY")
    result = (await admin.api.post(BASE + "/prices/estimate", json=body)).json()
    assert result["points"]["status"] == "currency_mismatch" and result["points"]["rates"] == {}
    assert result["points"]["total"] is None
    zero = await admin.api.post(
        BASE + "/point-prices/preview",
        json={"currency": "CNY", "input": "0", "cache_read": "0.000000000001"},
    )
    assert zero.status_code == 200
    assert zero.json()["rates"]["input"] == "0" and zero.json()["rates"]["output"] is None
    assert zero.json()["rates"]["cache_read"] == "0.0000000001"
    no_price = await create_model(admin, budget_price=None)
    assert no_price["point_price"]["status"] == "no_price"
    assert (
        await admin.api.post(
            BASE + "/prices/estimate",
            json={
                "price": {"currency": "CNY", "input": "0"},
                "usage": {"cache_read": 1},
                "include_points": True,
            },
        )
    ).status_code == 422


async def test_immutable_revisions_concurrent_edits_and_decimal_precision(env):
    admin = await env.client()
    original = await configure(admin, points_per_currency="0.000000000001")
    precise = (
        await admin.api.post(
            BASE + "/point-prices/preview", json=PRICE | {"input": "0.000000000001"}
        )
    ).json()
    assert precise["rates"]["input"] == "0.000000000000000000000001"
    same = await configure(admin, version=1, points_per_currency="0.000000000001")
    assert same == original
    responses = await asyncio.gather(
        *[
            admin.api.put(
                BASE + "/point-conversion",
                json={"currency": "USD", "version": 1, "points_per_currency": value},
            )
            for value in ("200", "300")
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    async with env.sessions() as db:
        rows = list(await db.scalars(select(PointConversion).order_by(PointConversion.version)))
        assert len(rows) == 2 and rows[0].points_per_currency == Decimal("0.000000000001")
        assert rows[0].id != rows[1].id
        assert await current_conversion(db, uuid4()) is None


async def test_validation_members_outsiders_csrf_and_anonymous_are_denied(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    outsider = await env.client(joined=False)
    for bad in ("0", "-1", "NaN", "1e3", "1000000000001", "0.0000000000001", 100):
        assert (
            await admin.api.put(
                BASE + "/point-conversion",
                json={"currency": "USD", "points_per_currency": bad, "version": 0},
            )
        ).status_code == 422
    body = {"currency": "USD", "points_per_currency": "100", "version": 0}
    for client in (member, outsider):
        assert (await client.api.get(BASE + "/point-conversion")).status_code == 403
        assert (await client.api.put(BASE + "/point-conversion", json=body)).status_code == 403
        assert (
            await client.api.post(BASE + "/point-prices/preview", json=PRICE)
        ).status_code == 403
    assert (
        await admin.api.put(
            BASE + "/point-conversion", json=body, headers={"x-csrf-token": "wrong"}
        )
    ).status_code == 403
    admin.api.cookies.clear()
    assert (await admin.api.get(BASE + "/point-conversion")).status_code == 401
