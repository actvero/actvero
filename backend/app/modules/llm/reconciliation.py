"""Canonical manual usage, snapshot arithmetic and management receipt identity."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from app.core.config import Settings
from app.modules.auth.service import now
from app.modules.desktop.errors import fail
from app.modules.llm import settlement
from app.modules.llm.catalog_schemas import TokenPrice
from app.modules.llm.models import UsageSettlement
from app.modules.llm.points import decimal_text
from app.modules.llm.reconciliation_schemas import (
    LegacyReconcileUsage,
    ReconcileInput,
    ReconciliationPreview,
    TaggedUsage,
)

_DOMAIN = b"actvero.llm.settlement.reconcile.v1\x00"
_TOKEN_FIELDS = {
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_5m_tokens",
    "cache_write_1h_tokens",
}
_SINGLE_FIELD = {
    "characters": "input_characters",
    "search_units": "search_units",
    "images": "image_count",
    "seconds": "audio_duration_ms",
}
_LEGACY_NAMES = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_tokens",
    "cache_write_5m": "cache_write_5m_tokens",
    "cache_write_1h": "cache_write_1h_tokens",
}


def required_fields(price: TokenPrice) -> list[str]:
    if price.metric != "tokens":
        return [_SINGLE_FIELD[price.metric]]
    result = ["input_tokens"]
    if price.output is not None:
        result.append("output_tokens")
    for rate in ("cache_read", "cache_write_5m", "cache_write_1h"):
        if getattr(price, rate) is not None:
            result.append(rate + "_tokens")
    return result


def available_after(row: UsageSettlement) -> datetime | None:
    if row.status == "reserved":
        return row.created_at + timedelta(minutes=10)
    return None


def eligible(row: UsageSettlement) -> bool:
    after = available_after(row)
    return row.status == "review" or bool(after is not None and after <= now())


def canonical_usage(price: TokenPrice, body: ReconcileInput) -> dict[str, int]:
    if body.action == "release":
        if body.usage is not None:
            fail(422, "invalid_release", "释放时不应填写用量")
        return {}
    if body.usage is None:
        fail(422, "usage_required", "结算须填写真实用量")
    required = set(required_fields(price))
    usage = body.usage
    if isinstance(usage, TaggedUsage):
        if usage.metric != price.metric:
            fail(422, "metric_mismatch", "用量计量类型与受理时价格不一致")
        allowed = _TOKEN_FIELDS if price.metric == "tokens" else {_SINGLE_FIELD[price.metric]}
        supplied = usage.model_fields_set - {"metric"}
        if not supplied <= allowed:
            fail(422, "metric_fields_mismatch", "用量字段与计量类型不一致")
        if not required <= supplied:
            fail(422, "usage_required", "请显式填写计价所需的真实用量，零用量也须填 0")
        result = {field: getattr(usage, field) for field in supplied}
    else:
        assert isinstance(usage, LegacyReconcileUsage)
        if price.metric == "seconds":
            fail(422, "metric_fields_mismatch", "转写核对须显式填写毫秒时长与 seconds 类型")
        supplied = usage.model_fields_set
        if price.metric == "tokens":
            result = {_LEGACY_NAMES[field]: getattr(usage, field) for field in supplied}
        else:
            if any(getattr(usage, field) != 0 for field in supplied - {"input"}):
                fail(422, "metric_fields_mismatch", "此计量类型只接受旧输入数量字段")
            result = {_SINGLE_FIELD[price.metric]: usage.input} if "input" in supplied else {}
        if not required <= result.keys():
            fail(422, "usage_required", "请显式填写计价所需的真实用量，零用量也须填 0")
    if any(value is None for value in result.values()):
        fail(422, "usage_required", "真实用量不能为空，零用量请填 0")
    if price.metric == "tokens":
        for field, rate_name in (
            ("output_tokens", "output"),
            ("cache_read_tokens", "cache_read"),
            ("cache_write_5m_tokens", "cache_write_5m"),
            ("cache_write_1h_tokens", "cache_write_1h"),
        ):
            if result.get(field, 0) > 0 and getattr(price, rate_name) is None:
                fail(422, "unknown_rate", "正用量对应单价未配置，无法结算")
    # Both DTOs enforce the range; preserve only explicitly supplied counts.
    return result


def preview(
    row: UsageSettlement, body: ReconcileInput, usage: dict[str, int]
) -> ReconciliationPreview:
    price = TokenPrice.model_validate(row.price)
    amount = Decimal(0) if body.action == "release" else settlement.amount_for(price, usage)
    if amount is None:
        fail(422, "unknown_rate", "用量对应单价未配置，无法结算")
    return ReconciliationPreview(
        call_id=row.id,
        version=row.version,
        action=body.action,
        metric=price.metric,
        usage=usage,
        amount=decimal_text(amount),
        points=decimal_text(settlement.points(amount, row.ratio)),
        currency=row.currency,
    )


def receipt_digest(
    settings: Settings, call_id: UUID, body: ReconcileInput, usage: dict[str, int]
) -> str:
    secret = settings.session_encryption_key
    if secret is None:
        fail(503, "receipt_key_unavailable", "核对回执密钥尚未配置")
    payload = {
        "call_id": str(call_id),
        "version": body.version,
        "action": body.action,
        "usage": usage,
        "reason": body.reason.strip(),
    }
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode()
    return hmac.new(
        secret.get_secret_value().encode(), _DOMAIN + encoded, hashlib.sha256
    ).hexdigest()
