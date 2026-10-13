"""Pure automatic settlement gate: no database, vendor, or SDK network request."""

from decimal import Decimal

from app.modules.llm.catalog_schemas import TokenPrice
from app.modules.llm.settlement import amount_for
from app.modules.llm.settlement_evidence import evaluate, observed_usage


def price(metric="tokens", **rates):
    return TokenPrice.model_validate(
        {
            "currency": "USD",
            "metric": metric,
            "unit": 1 if metric == "images" else 1000000,
            "input": "1",
            **rates,
        }
    )


def evidence(field, value, attempt_id="one", *, source="upstream", phase="terminal", complete=True):
    metric = {
        "input_characters": "characters",
        "search_units": "searches",
        "image_count": "images",
    }.get(field, "tokens")
    return {
        "field": field,
        "value": value,
        "metric": metric,
        "source": source,
        "complete": complete,
        "phase": phase,
        "attempt_id": attempt_id,
        "evidence_version": 1,
    }


def attempt(
    attempt_id="one", *, fields=(), sent=True, status="succeeded", terminal=True, uncertain=False
):
    return {
        "attempt_id": attempt_id,
        "evidence_version": 1,
        "sent": sent,
        "status": status,
        "upstream_terminal": terminal,
        "uncertain": uncertain,
        "usage_evidence": list(fields),
        "usage": {"cache_read_tokens": 0},
    }


def chat_fields(attempt_id="one", *, inp=100, out=20):
    return [
        evidence("input_tokens", inp, attempt_id),
        evidence("output_tokens", out, attempt_id),
        evidence("raw_prompt_tokens", inp, attempt_id),
        evidence("raw_completion_tokens", out, attempt_id),
    ]


def test_chat_omitted_cache_can_price_verified_whole_input_without_fake_raw_zero():
    row = attempt(fields=chat_fields())
    result = evaluate(price(output="2"), [row], delivered=True)
    assert result.action == "settle" and result.reason == "verified_usage"
    assert result.usage == {
        "input_tokens": 100,
        "output_tokens": 20,
    }
    assert len(result.metadata["assumptions"]) == 3
    assert result.metadata["decision"] == "settle"
    assert result.metadata["reason"] == "verified_usage"
    assert result.metadata["metric"] == "tokens"
    assert result.metadata["attempts"][0]["fields"] == [
        {
            "field": entry["field"],
            "value": entry["value"],
            "metric": "tokens",
            "source": "upstream",
            "complete": True,
            "phase": "terminal",
            "evidence_version": 1,
        }
        for entry in chat_fields()
    ]
    assert "usage" not in result.metadata["attempts"][0]


def test_priced_cache_requires_explicit_raw_even_when_price_is_zero():
    priced = price(output="2", cache_read="0")
    assert (
        evaluate(priced, [attempt(fields=chat_fields())], delivered=True).reason
        == "priced_cache_missing"
    )
    fields = chat_fields() + [evidence("cache_read_tokens", 0)]
    result = evaluate(priced, [attempt(fields=fields)], delivered=True)
    assert result.action == "settle" and result.usage["cache_read_tokens"] == 0


def test_positive_unpriced_cache_and_bad_raw_decomposition_require_review():
    fields = [*chat_fields(inp=90), evidence("cache_read_tokens", 10)]
    assert (
        evaluate(price(output="2"), [attempt(fields=fields)], delivered=True).reason
        == "unpriced_cache_positive"
    )
    fields = chat_fields(inp=90)
    fields[2] = evidence("raw_prompt_tokens", 100)
    assert (
        evaluate(price(output="2"), [attempt(fields=fields)], delivered=True).reason
        == "cache_decomposition_mismatch"
    )
    no_total = fields[:2]
    assert (
        evaluate(price(output="2"), [attempt(fields=no_total)], delivered=True).reason
        == "cache_decomposition_unknown"
    )


def test_sdk_synthetic_zero_partial_usage_and_conflict_never_settle():
    synthetic = attempt(fields=chat_fields()[:1])
    assert (
        evaluate(price(output="2"), [synthetic], delivered=True).reason == "output_tokens_missing"
    )
    partial = attempt(fields=[evidence("input_tokens", 100, phase="partial"), *chat_fields()[1:]])
    assert evaluate(price(output="2"), [partial], delivered=True).reason == "input_tokens_missing"
    conflict = attempt(fields=[*chat_fields(), evidence("input_tokens", 101)])
    assert evaluate(price(output="2"), [conflict], delivered=True).reason == "evidence_conflict"
    malformed = attempt(fields=[*chat_fields(), {"field": [], "phase": []}])
    assert evaluate(price(output="2"), [malformed], delivered=True).action == "settle"


def test_unknown_prior_attempt_is_not_covered_by_successful_last_attempt():
    prior = attempt("prior", fields=(), status="failed", terminal=False, uncertain=True)
    final = attempt("final", fields=chat_fields("final"))
    review = evaluate(price(output="2"), [prior, final], delivered=True)
    assert review.reason == "execution_unknown"
    assert review.usage["output_tokens"] == 20
    assert review.metadata["usage_scope"] == "last_attempt_observed"
    prior["sent"] = None
    assert evaluate(price(output="2"), [prior, final], delivered=True).reason == "send_unknown"
    prior["sent"] = False
    result = evaluate(price(output="2"), [prior, final], delivered=True)
    assert result.action == "settle" and result.usage["input_tokens"] == 100


def test_multiple_verified_attempts_are_summed_before_amount_calculation():
    first = attempt("first", fields=chat_fields("first", inp=70, out=9), status="failed")
    second = attempt("second", fields=chat_fields("second", inp=30, out=11))
    result = evaluate(price(output="2"), [first, second], delivered=True)
    assert result.action == "settle"
    assert result.usage["input_tokens"] == 100 and result.usage["output_tokens"] == 20
    first["usage_evidence"] = []
    assert (
        evaluate(price(output="2"), [first, second], delivered=True).reason
        == "input_tokens_missing"
    )


def test_only_certain_no_send_releases_and_delivery_failure_reviews():
    before = attempt(fields=(), sent=False, status="failed", terminal=False, uncertain=False)
    assert evaluate(price(output="2"), [before], delivered=False).action == "release"
    assert (
        evaluate(price(output="2"), [before], delivered=True).reason
        == "delivery_conflicts_with_no_send"
    )
    assert (
        evaluate(price(output="2"), [attempt(fields=chat_fields())], delivered=False).reason
        == "delivery_unconfirmed"
    )
    assert evaluate(price(output="2"), [], delivered=False).reason == "attempts_missing"


def test_metric_specific_sources_and_confirmed_success():
    characters = attempt(fields=[evidence("input_characters", 5, source="validated_input")])
    assert evaluate(price("characters"), [characters], delivered=True).usage == {
        "input_characters": 5
    }
    characters["status"] = "failed"
    assert evaluate(price("characters"), [characters], delivered=True).reason == "execution_unknown"
    searches = attempt(fields=[evidence("search_units", 3)])
    assert evaluate(price("search_units"), [searches], delivered=True).usage == {"search_units": 3}
    searches["upstream_terminal"] = False
    assert (
        evaluate(price("search_units"), [searches], delivered=True).reason
        == "upstream_terminal_missing"
    )
    images = attempt(
        fields=[
            evidence("image_count", 1, source="confirmed_delivery", phase="confirmed_delivery")
        ],
        terminal=False,
    )
    assert evaluate(price("images"), [images], delivered=True).usage == {"image_count": 1}


def test_token_terminal_raw_output_and_required_cache_guards():
    row = attempt(fields=chat_fields(), terminal=False)
    assert evaluate(price(output="2"), [row], delivered=True).reason == "upstream_terminal_missing"
    row = attempt(fields=chat_fields())
    row["usage_evidence"][3]["value"] = 21
    assert evaluate(price(output="2"), [row], delivered=True).reason == "output_tokens_mismatch"
    assert (
        evaluate(price(cache_read="1"), [attempt(fields=chat_fields()[:1])], delivered=True).reason
        == "priced_cache_missing"
    )


def test_input_only_token_prices_include_explicit_cache_without_output_price():
    rates = price(cache_read="2")
    fields = [
        evidence("input_tokens", 100),
        evidence("raw_prompt_tokens", 150),
        evidence("cache_read_tokens", 50),
    ]
    result = evaluate(rates, [attempt(fields=fields)], delivered=True)
    assert result.action == "settle"
    assert result.usage == {"input_tokens": 100, "cache_read_tokens": 50}
    assert amount_for(rates, result.usage) == Decimal("0.0002")
    assert amount_for(rates, {"input_tokens": 100}) is None
    assert amount_for(price(), result.usage) is None


def test_malformed_or_legacy_attempt_cannot_auto_release_or_settle():
    assert evaluate(price(output="2"), [{"sent": False}], delivered=False).action == "review"
    assert evaluate(price(output="2"), [42], delivered=False).reason == "attempts_invalid"
    row = attempt(fields=chat_fields())
    row["usage_evidence"][0]["phase"] = []
    assert evaluate(price(output="2"), [row], delivered=True).reason == "input_tokens_missing"
    row = attempt(fields=chat_fields())
    row["usage_evidence"][0]["metric"] = "characters"
    assert evaluate(price(output="2"), [row], delivered=True).reason == "input_tokens_missing"


def test_review_projection_prefers_terminal_and_omits_conflict_and_synthetic_zero():
    fields = [
        evidence("input_tokens", 5, phase="partial", complete=False),
        evidence("input_tokens", 7),
        evidence("output_tokens", 2, phase="partial", complete=False),
        evidence("output_tokens", 3, phase="partial", complete=False),
        evidence("cache_read_tokens", 0, source="unknown"),
        evidence("image_count", 1, source="confirmed_delivery", phase="confirmed_delivery"),
    ]
    row = attempt(fields=fields, status="failed", terminal=False, uncertain=True)
    assert observed_usage([row]) == {"input_tokens": 7, "image_count": 1}
    review = evaluate(price(output="2"), [row], delivered=False)
    assert review.action == "review" and review.usage == observed_usage([row])
    assert review.metadata["usage_scope"] == "last_attempt_observed"


def test_review_projection_from_last_attempt_only_and_no_raw_body():
    previous = attempt("before", fields=chat_fields("before", inp=8, out=3))
    last = attempt("last", fields=[evidence("input_tokens", 5, "last")], status="failed")
    last["usage"] = {"output_tokens": 0, "secret": "do not persist"}
    assert observed_usage([previous, last]) == {"input_tokens": 5}
    review = evaluate(price(output="2"), [previous, last], delivered=False)
    assert review.usage == {"input_tokens": 5}
    assert "secret" not in str(review.metadata)


def test_settled_image_preserves_complete_raw_token_observations_without_pricing_them():
    row = attempt(
        fields=[
            evidence("image_count", 1, source="confirmed_delivery", phase="confirmed_delivery"),
            evidence("input_tokens", 5),
            evidence("output_tokens", 7),
        ]
    )
    result = evaluate(price("images"), [row], delivered=True)
    assert result.action == "settle"
    assert result.usage == {"image_count": 1, "input_tokens": 5, "output_tokens": 7}
    assert result.metadata["auxiliary_fields"] == ["input_tokens", "output_tokens"]
    assert result.metadata["usage_scope"] == "all_confirmed_attempts"


def test_auxiliary_meter_requires_each_sent_attempt_and_never_fills_missing_with_zero():
    first = attempt(
        "first",
        fields=[
            evidence("image_count", 1, "first", source="confirmed_delivery"),
            evidence("input_tokens", 5, "first"),
            evidence("output_tokens", 7, "first"),
        ],
    )
    second = attempt(
        "second",
        fields=[
            evidence("image_count", 1, "second", source="confirmed_delivery"),
            evidence("input_tokens", 6, "second"),
            evidence("output_tokens", 8, "second", phase="partial", complete=False),
        ],
    )
    result = evaluate(price("images"), [first, second], delivered=True)
    assert result.action == "settle"
    assert result.usage == {"image_count": 2, "input_tokens": 11}
    second["usage_evidence"].append(evidence("input_tokens", 9, "second"))
    result = evaluate(price("images"), [first, second], delivered=True)
    assert result.action == "settle"
    assert result.usage == {"image_count": 2}
