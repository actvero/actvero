"""Named native route presets and reviewed supplier list-price defaults."""

import json
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request

from app.modules.model_gateway import client

ARK_ORIGIN = "https://ark.cn-beijing.volces.com"
ARK_PLAN_ROUTES = {
    "/v1/chat/completions": ("/api/plan/v3/chat/completions", "none"),
    "/v1/messages": ("/api/plan/v1/messages", "none"),
    "/v1/responses": (
        "/api/plan/v3/chat/completions",
        "openai_responses_to_openai_chat_completions",
    ),
}
ARK_PEAK = (
    'weekday("Asia/Shanghai") >= 1 && weekday("Asia/Shanghai") <= 5 && '
    '((hour("Asia/Shanghai") >= 9 && hour("Asia/Shanghai") < 12) || '
    '(hour("Asia/Shanghai") >= 14 && hour("Asia/Shanghai") < 18))'
)


@lru_cache(maxsize=1)
def official_catalog() -> dict[str, Any]:
    catalog: dict[str, Any] = json.loads(Path(__file__).with_name("ark_prices.json").read_text())
    return catalog


def is_ark_plan_template(channel: dict[str, Any]) -> bool:
    if channel.get("type") != 58 or channel.get("base_url") != ARK_ORIGIN:
        return False
    try:
        settings = (
            json.loads(channel["settings"])
            if channel.get("settings")
            else {"advanced_custom": json.loads(channel.get("advanced_custom") or "{}")}
        )
        routes = settings["advanced_custom"]["advanced_routes"]
        actual = {
            route["incoming_path"]: (route["upstream_path"], route.get("converter", "none"))
            for route in routes
            if not route.get("models")
        }
        return actual == ARK_PLAN_ROUTES and len(routes) == len(ARK_PLAN_ROUTES)
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def price_expression(name: str, usd_to_cny: Decimal) -> str:
    rates = official_catalog()["models"][name]
    if not usd_to_cny.is_finite() or usd_to_cny <= 0:
        raise ValueError("A positive native CNY exchange rate is required")
    rate = format(usd_to_cny, "f")

    def tier(values: dict[str, Any], label: str) -> str:
        terms = [
            f"p * {values['input']}",
            f"cr * {values['cached_input']}",
            f"c * {values['output']}",
        ]
        # Actvero's chat contract accepts text and images. Audio tariffs remain
        # in the source snapshot, not in a partially supported cache expression.
        return f'tier("ark_{label}_20261024", ({" + ".join(terms)}) / {rate})'

    if "peak" in rates:
        return f"{ARK_PEAK} ? {tier(rates['peak'], 'peak')} : {tier(rates, 'off_peak')}"
    return tier(rates, "standard")


async def initialize_official_prices(
    request: Request, tenant_id: UUID, channel: dict[str, Any]
) -> dict[str, Any] | None:
    if not is_ark_plan_template(channel):
        return None
    names = list(
        dict.fromkeys(
            name.strip() for name in (channel.get("models") or "").split(",") if name.strip()
        )
    )
    catalog = official_catalog()
    known = [name for name in names if name in catalog["models"]]
    result: dict[str, Any] = {
        "applied": [],
        "preserved": [],
        "unavailable": [name for name in names if name not in catalog["models"]],
        "source": catalog["source"],
        "verified_at": catalog["verified_at"],
        "currency": "CNY",
        "pending": False,
    }
    if not known:
        return result
    try:
        status = await client.call(request, tenant_id, "GET", "/api/status")
        fx = Decimal(str(status.get("usd_exchange_rate")))
        if not fx.is_finite() or fx <= 0:
            raise ValueError
        snapshot = await client.call(
            request, tenant_id, "GET", "/api/option/model_pricing", params={"model": known}
        )
        entries = {entry["model_name"]: entry for entry in snapshot["entries"]}
        changes = []
        for name in known:
            entry = entries[name]
            configured = entry["configured"]
            # Native inherited prices may belong to a different supplier.
            # An explicit organization price, including free pricing, is retained.
            if configured:
                result["preserved"].append(name)
                continue
            changes.append(
                {
                    "model_name": name,
                    "expected_version": entry["version"],
                    "pricing": {
                        "billing_setting.billing_mode": "tiered_expr",
                        "billing_setting.billing_expr": price_expression(name, fx),
                    },
                }
            )
        if changes:
            await client.call(
                request,
                tenant_id,
                "PATCH",
                "/api/option/model_pricing",
                payload={"changes": changes},
            )
            result["applied"] = [change["model_name"] for change in changes]
        result["usd_exchange_rate"] = str(fx)
    except (HTTPException, ValueError, InvalidOperation, KeyError, TypeError, AttributeError):
        # The channel has already been saved. Do not turn a failed price import
        # into an uncertain save or expose an upstream response in a warning.
        result["pending"] = True
    return result
