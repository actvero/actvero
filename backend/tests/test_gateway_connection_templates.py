"""Native route templates use supplier-specific prices and preserve member pricing."""

import json
from decimal import Decimal
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from app.modules.model_gateway import client
from app.modules.model_gateway.connection_templates import (
    ARK_ORIGIN,
    ARK_PLAN_ROUTES,
    initialize_official_prices,
    is_ark_plan_template,
    price_expression,
)


def plan_channel(**updates):
    return {
        "type": 58,
        "base_url": ARK_ORIGIN,
        "models": "doubao-seed-2.1-pro,deepseek-v4-pro,glm-5.3,kimi-k3.1-pro",
        "settings": json.dumps(
            {
                "advanced_custom": {
                    "advanced_routes": [
                        {"incoming_path": incoming, "upstream_path": path, "converter": converter}
                        for incoming, (path, converter) in ARK_PLAN_ROUTES.items()
                    ]
                }
            }
        ),
        **updates,
    }


def test_ark_template_cannot_match_an_arbitrary_destination_or_protocol():
    assert is_ark_plan_template(plan_channel())
    assert is_ark_plan_template(
        {
            "type": 58,
            "base_url": ARK_ORIGIN,
            "advanced_custom": json.dumps(
                json.loads(plan_channel()["settings"])["advanced_custom"]
            ),
        }
    )
    for update in (
        {"type": 1},
        {"base_url": "https://proxy.example"},
        {"settings": "broken"},
        {"settings": "null"},
    ):
        assert not is_ark_plan_template(plan_channel(**update))
    channel = plan_channel()
    settings = json.loads(channel["settings"])
    settings["advanced_custom"]["advanced_routes"][0]["upstream_path"] = "https://unrelated.example"
    channel["settings"] = json.dumps(settings)
    assert not is_ark_plan_template(channel)


def test_list_price_expression_keeps_cny_rate_and_supplier_cache_prices():
    expr = price_expression("doubao-seed-2.1-pro", Decimal("7.3"))
    assert "p * 6 + cr * 1.2 + c * 30" in expr
    assert "/ 7.3" in expr
    expr = price_expression("deepseek-v4-pro", Decimal("7.3"))
    assert "p * 9 + cr * 0.3 + c * 27" in expr
    assert "weekday" not in expr  # Ark Pro does not use DeepSeek's own time tariffs.
    expr = price_expression("deepseek-v4.1-flash", Decimal("7.3"))
    assert 'weekday("Asia/Shanghai")' in expr
    assert "p * 2 + cr * 0.04 + c * 8" in expr
    assert "p * 1 + cr * 0.02 + c * 4" in expr
    with pytest.raises(ValueError):
        price_expression("doubao-seed-2.1-pro", Decimal(0))


@pytest.mark.asyncio
async def test_template_initializes_exact_matches_without_overwriting_custom_prices(monkeypatch):
    calls = []
    owner = uuid4()

    async def native(request, tenant, method, path, **kwargs):
        assert tenant == owner
        calls.append((method, path, kwargs))
        if path == "/api/status":
            return {"usd_exchange_rate": 7.3}
        if method == "GET":
            return {
                "entries": [
                    {"model_name": name, "version": name + "-version", "configured": configured}
                    for name, configured in (
                        ("doubao-seed-2.1-pro", {}),
                        ("deepseek-v4-pro", {"ModelRatio": 0}),
                        ("kimi-k3.1-pro", {}),
                    )
                ]
            }
        return {"updated_models": ["doubao-seed-2.1-pro", "kimi-k3.1-pro"]}

    monkeypatch.setattr(client, "call", native)
    result = await initialize_official_prices(Request({"type": "http"}), owner, plan_channel())
    assert result["applied"] == ["doubao-seed-2.1-pro", "kimi-k3.1-pro"]
    assert result["preserved"] == ["deepseek-v4-pro"]
    assert result["unavailable"] == ["glm-5.3"]
    changes = calls[-1][2]["payload"]["changes"]
    assert len(changes) == 2
    assert changes[0]["expected_version"] == "doubao-seed-2.1-pro-version"
    assert "13" in changes[1]["pricing"]["billing_setting.billing_expr"]


@pytest.mark.asyncio
@pytest.mark.parametrize("rate", [None, "NaN", -1, 0, "invalid"])
async def test_failed_import_does_not_report_the_saved_channel_as_failed(monkeypatch, rate):
    call = AsyncMock(return_value={"usd_exchange_rate": rate})
    monkeypatch.setattr(client, "call", call)
    result = await initialize_official_prices(Request({"type": "http"}), uuid4(), plan_channel())
    assert result["pending"] is True
    assert result["applied"] == []
    assert call.await_count == 1


@pytest.mark.asyncio
async def test_price_conflict_is_reported_without_leaking_supplier_errors(monkeypatch):
    monkeypatch.setattr(client, "call", AsyncMock(side_effect=HTTPException(409, "private-secret")))
    result = await initialize_official_prices(Request({"type": "http"}), uuid4(), plan_channel())
    assert result["pending"] is True
    assert "secret" not in json.dumps(result)


@pytest.mark.asyncio
async def test_ordinary_channels_never_trigger_price_changes(monkeypatch):
    call = AsyncMock()
    monkeypatch.setattr(client, "call", call)
    assert (
        await initialize_official_prices(Request({"type": "http"}), uuid4(), plan_channel(type=1))
        is None
    )
    call.assert_not_awaited()
