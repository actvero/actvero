"""Metric-specific manual reconciliation is explicit and non-replayable."""

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.modules.desktop.errors import DesktopError
from app.modules.llm.catalog_schemas import TokenPrice
from app.modules.llm.reconciliation import canonical_usage, preview, receipt_digest, required_fields
from app.modules.llm.reconciliation_schemas import ReconcileInput


def request(usage: dict | None, **overrides) -> ReconcileInput:
    return ReconcileInput.model_validate(
        {
            "version": 2,
            "request_id": str(uuid4()),
            "action": "settle",
            "usage": usage,
            "reason": "supplier statement",
            **overrides,
        }
    )


def price(**overrides) -> TokenPrice:
    return TokenPrice.model_validate({"currency": "USD", "input": "1", **overrides})


def rejects(price_value: TokenPrice, body: ReconcileInput, code: str) -> None:
    with pytest.raises(DesktopError) as error:
        canonical_usage(price_value, body)
    assert error.value.status_code == 422 and error.value.code == code


def test_priced_zero_cache_is_required_and_never_implicit() -> None:
    configured = price(output="2", cache_read="0")
    assert required_fields(configured) == ["input_tokens", "output_tokens", "cache_read_tokens"]
    rejects(
        configured,
        request({"metric": "tokens", "input_tokens": 12, "output_tokens": 3}),
        "usage_required",
    )
    explicit = request(
        {"metric": "tokens", "input_tokens": 12, "output_tokens": 3, "cache_read_tokens": 0}
    )
    assert canonical_usage(configured, explicit) == {
        "input_tokens": 12,
        "output_tokens": 3,
        "cache_read_tokens": 0,
    }
    rejects(
        price(output="2"),
        request(
            {"metric": "tokens", "input_tokens": 12, "output_tokens": 3, "cache_read_tokens": 1}
        ),
        "unknown_rate",
    )


def test_input_only_token_price_with_priced_cache_is_supported() -> None:
    configured = price(cache_read="0.5")
    assert required_fields(configured) == ["input_tokens", "cache_read_tokens"]
    body = request({"metric": "tokens", "input_tokens": 10, "cache_read_tokens": 2})
    usage = canonical_usage(configured, body)
    assert usage == {"input_tokens": 10, "cache_read_tokens": 2}
    row = SimpleNamespace(
        id=uuid4(),
        version=2,
        price=configured.model_dump(mode="json"),
        ratio=Decimal("10"),
        currency="USD",
    )
    assert preview(row, body, usage).amount == "0.000011"


@pytest.mark.parametrize(
    "metric,field",
    [
        ("characters", "input_characters"),
        ("search_units", "search_units"),
        ("images", "image_count"),
    ],
)
def test_each_metric_accepts_only_its_explicit_count(metric: str, field: str) -> None:
    configured = price(metric=metric, unit=1 if metric == "images" else 1000000)
    assert required_fields(configured) == [field]
    assert canonical_usage(configured, request({"metric": metric, field: 0})) == {field: 0}
    rejects(configured, request({"metric": metric}), "usage_required")
    rejects(configured, request({"metric": "tokens", "input_tokens": 1}), "metric_mismatch")
    rejects(
        configured,
        request({"metric": metric, field: 1, "input_tokens": 1}),
        "metric_fields_mismatch",
    )


@pytest.mark.parametrize("invalid", [True, 1.5, "1", None, -1, 10**12 + 1])
def test_tagged_and_legacy_counts_reject_noninteger_or_out_of_bounds(invalid: object) -> None:
    for payload, configured in (
        ({"metric": "characters", "input_characters": invalid}, price(metric="characters")),
        ({"input": invalid}, price(metric="characters")),
    ):
        if invalid is None:
            rejects(configured, request(payload), "usage_required")
        else:
            with pytest.raises(ValueError):
                request(payload)


def test_legacy_uses_only_supplied_fields_and_rejects_mixed_names() -> None:
    configured = price(output="2", cache_read="0")
    rejects(configured, request({"input": 1, "output": 2}), "usage_required")
    legacy = request({"input": 1, "output": 2, "cache_read": 0})
    assert canonical_usage(configured, legacy) == {
        "input_tokens": 1,
        "output_tokens": 2,
        "cache_read_tokens": 0,
    }
    chars = price(metric="characters")
    assert canonical_usage(chars, request({"input": 3, "output": 0, "cache_read": 0})) == {
        "input_characters": 3
    }
    rejects(chars, request({"input": 3, "output": 1}), "metric_fields_mismatch")
    with pytest.raises(ValueError):
        request({"metric": "tokens", "input_tokens": 1, "input": 1})
    with pytest.raises(ValueError):
        request({"metric": "images", "image_count": 1, "cache_read": 0})


def test_preview_uses_snapshots_and_hmac_canonicalizes_legacy_and_tagged() -> None:
    configured = price(output="2", cache_read="0")
    row = SimpleNamespace(
        id=uuid4(),
        version=2,
        price=configured.model_dump(mode="json"),
        ratio=Decimal("12.5"),
        currency="USD",
    )
    tagged = request(
        {"metric": "tokens", "input_tokens": 12, "output_tokens": 3, "cache_read_tokens": 0}
    )
    legacy = request({"cache_read": 0, "output": 3, "input": 12}, request_id=str(uuid4()))
    usage = canonical_usage(configured, tagged)
    calculation = preview(row, tagged, usage)
    assert calculation.amount == "0.000018"
    assert calculation.points == "0.000225"
    assert calculation.usage == usage and calculation.version == 2
    settings = Settings(_env_file=None, session_encryption_key=Fernet.generate_key().decode())
    digest = receipt_digest(settings, row.id, tagged, usage)
    assert digest == receipt_digest(settings, row.id, legacy, canonical_usage(configured, legacy))
    assert len(digest) == 64 and "supplier statement" not in digest
    assert digest != receipt_digest(settings, uuid4(), tagged, usage)
    assert digest != receipt_digest(
        settings, row.id, tagged.model_copy(update={"version": 3}), usage
    )
    assert digest != receipt_digest(
        settings, row.id, tagged.model_copy(update={"reason": "different"}), usage
    )
    release = request(None, action="release")
    released = preview(row, release, canonical_usage(configured, release))
    assert released.amount == released.points == "0" and released.usage == {}
