"""Correlate native billing evidence. Missing or estimated usage never means free."""

import asyncio
import json
import time
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID

from fastapi import Request

from app.modules.auth.service import now
from app.modules.llm.models import ModelCall, UsageSettlement
from app.modules.model_gateway import client
from app.modules.model_gateway.publication import origin_hash

CONFIRMED_PATHS = {"billing-usage-openai", "billing-usage-anthropic", "billing-usage-gemini"}


def verified_ledger(entry: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any] | None:
    reference = attempt.get("gateway") or {}
    if (
        entry.get("request_id") != attempt.get("gateway_request_id")
        or entry.get("token_id") != reference.get("token_id")
        or entry.get("model_name") != attempt.get("upstream_id")
        or entry.get("type") != 2
    ):
        return None
    try:
        other = json.loads(entry.get("other") or "{}")
        admin = other.get("admin_info") or {}
    except (TypeError, ValueError, AttributeError):
        return None
    path = admin.get("usage_billing_path")
    if (
        (
            path not in CONFIRMED_PATHS
            and not (path == "upstream" and admin.get("actvero_upstream_usage_confirmed") is True)
        )
        or admin.get("local_count_tokens")
        or admin.get("quota_saturation")
    ):
        return None
    quota = entry.get("quota")
    if type(quota) is not int or not 0 <= quota <= 2**53:
        return None
    if any(
        type(entry.get(k)) is not int or entry[k] < 0
        for k in ("prompt_tokens", "completion_tokens")
    ):
        return None
    # Empty token usage can be the native fallback after a missing usage response.
    if entry["prompt_tokens"] + entry["completion_tokens"] == 0:
        return None
    return {
        "request_id": entry["request_id"],
        "log_id": entry["id"],
        "token_id": entry["token_id"],
        "model": entry["model_name"],
        "channel_id": entry.get("channel"),
        "quota": quota,
        "quota_per_unit": reference["quota_per_unit"],
        "billing_path": path,
        "input_tokens": entry["prompt_tokens"],
        "output_tokens": entry["completion_tokens"],
    }


async def reconcile(request: Request, record: dict[str, Any]) -> bool:
    """Return false while an asynchronous native log may still arrive."""
    attempts = record.get("attempts", [])
    gateway_attempts = [a for a in attempts if a.get("gateway")]
    if not gateway_attempts or not record.get("complete"):
        return True
    config = client.connection(request, UUID(record["tenant_id"]))
    waiting = False
    for attempt in gateway_attempts:
        if attempt.get("gateway_ledger"):
            continue
        ref = attempt["gateway"]
        request_id = attempt.get("gateway_request_id")
        if not request_id or not config or origin_hash(config.base_url) != ref.get("origin_hash"):
            continue
        try:
            async with asyncio.timeout(2):
                result = await client.call(
                    request,
                    UUID(record["tenant_id"]),
                    "GET",
                    "/api/log/",
                    params={"request_id": request_id, "type": 2, "page_size": 100},
                )
            entries = result.get("items", [])
            matching = [e for e in entries if e.get("request_id") == request_id]
            if not matching:
                waiting = True
                continue
            if len(matching) == 1:
                ledger = verified_ledger(matching[0], attempt)
                if ledger:
                    attempt["gateway_ledger"] = ledger
        except (Exception, TimeoutError):
            waiting = True
    return not waiting or time.time() >= record.get("gateway_billing_deadline", 0)


def complete(row: UsageSettlement, log: ModelCall | None, *, certainly_unused: bool) -> None:
    attempts = log.attempts if log else []
    if certainly_unused and not attempts:
        row.amount, row.status = Decimal(0), "released"
        row.evidence = {"engine": "newapi", "decision": "release", "reason": "no_dispatch"}
    elif len(attempts) == 1 and (ledger := attempts[0].get("gateway_ledger")):
        with localcontext() as ctx:
            ctx.prec = 80
            row.amount = Decimal(ledger["quota"]) / Decimal(str(ledger["quota_per_unit"]))
        row.status = "settled"
        row.usage = {
            "source": "upstream",
            "input_tokens": ledger["input_tokens"],
            "output_tokens": ledger["output_tokens"],
        }
        row.evidence = {"engine": "newapi", "decision": "settle", "ledger": ledger}
    else:
        row.status = "review"
        row.reason = "未取得可确认的 New API 账单；预留额度保留，未按零费用结算"
        row.evidence = {
            "engine": "newapi",
            "decision": "review",
            "reason": "native_billing_unconfirmed",
        }
    row.version += 1
    if row.status in {"settled", "released"}:
        row.settled_at = now()
