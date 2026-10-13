"""Pure catalog projection and query checks; no database or upstream request."""

import json
from datetime import UTC, datetime
from decimal import Decimal

from app.modules.llm import reference_catalog as reference


def catalog() -> list[reference.ReferenceModel]:
    data = {
        "anthropic": {
            "name": "Anthropic",
            "doc": "https://docs.anthropic.com/models",
            "models": {
                "claude-v": {
                    "name": "Claude V",
                    "canonical_model_id": "anthropic/claude-v",
                    "tool_call": True,
                    "structured_output": False,
                    "reasoning": True,
                    "reasoning_options": [{"type": "toggle"}],
                    "temperature": False,
                    "limit": {"context": 200000, "input": 180000, "output": 10000},
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                    "family": "claude",
                    "release_date": "2026-09-02",
                    "last_updated": "2026-09-20",
                    "knowledge": "2026-08",
                    "cost": {"input": 3, "output": 15, "cache_read": 0.3},
                    "links": [{"type": "docs", "url": "https://docs.anthropic.com/claude-v"}],
                }
            },
        },
        "relay": {
            "name": "Relay",
            "doc": "https://127.0.0.1/private",
            "models": {
                "claude-v": {
                    "name": "Claude V Relay",
                    "canonical_model_id": "anthropic/claude-v",
                    "tool_call": True,
                    "limit": {"context": 100000, "output": 8000},
                    "status": "beta",
                    "cost": {"input": 2, "output": 10},
                },
                "cheap-complex": {
                    "name": "Cheap Complex",
                    "tool_call": False,
                    "reasoning": False,
                    "status": "alpha",
                    "release_date": "2026-10-01",
                    "cost": {
                        "input": 0.000000000001,
                        "output": 0.1,
                        "cache_write": 0.25,
                        "reasoning": 0.5,
                        "input_audio": 1.1,
                        "output_audio": 1.2,
                        "tiers": [
                            {"tier": {"type": "context", "size": 200000}, "input": 4, "output": 8}
                        ],
                        "context_over_200k": {"input": 5, "output": 9},
                        "unrecognized_dimension": {"amount": 0.000000000002},
                    },
                },
                "partial": {
                    "name": "Partial",
                    "cost": {"input": 1},
                    "status": "deprecated",
                },
                "unknown": {"name": "Unknown", "tool_call": False},
            },
        },
    }
    payload = json.dumps(data).replace("1e-12", "0.000000000001").replace("2e-12", "0.000000000002")
    models, skipped = reference.parse_catalog(payload.encode())
    assert skipped == 0
    return models


def find(models: list[reference.ReferenceModel], model_id: str) -> reference.ReferenceModel:
    return next(model for model in models if model.model_id == model_id)


def test_projection_uses_canonical_lab_and_safe_source_without_guessing():
    models = catalog()
    original = next(m for m in models if m.provider == "anthropic")
    relay = next(m for m in models if m.provider == "relay" and m.model_id == "claude-v")
    unknown = find(models, "unknown")
    assert relay.canonical_model_id == "anthropic/claude-v"
    assert relay.developer == "anthropic" and relay.developer_name == "Anthropic"
    assert unknown.developer is None and unknown.canonical_model_id is None
    assert original.family == "claude"
    assert original.max_input == 180000
    assert original.input_modalities == ["text", "image"]
    assert original.output_modalities == ["text"]
    assert original.temperature == "unsupported"
    assert original.release_date == "2026-09-02"
    assert original.last_updated == "2026-09-20"
    assert original.knowledge == "2026-08"
    assert original.source_url == "https://docs.anthropic.com/claude-v"
    assert relay.source_url is None
    assert unknown.status is None and unknown.capabilities.tools == "unsupported"
    assert reference.safe_document_url("https://name:secret@example.com/a") is None
    assert reference.safe_document_url("https://127.0.0.1/a") is None


def test_price_conditions_are_complete_and_decimal_exact():
    models = catalog()
    complex_model = find(models, "cheap-complex")
    assert complex_model.price is not None
    assert complex_model.price.input == Decimal("0.000000000001")
    assert complex_model.price_importable is False
    conditions = " ".join(complex_model.price_conditions)
    for term in (
        "缓存写入",
        "思考",
        "音频输入",
        "音频输出",
        "上下文阶梯",
        "超过 200K",
        "unrecognized_dimension",
        "0.000000000002",
    ):
        assert term in conditions
    assert "仅导入基础单价" not in " ".join(complex_model.price_notes)
    assert find(models, "partial").price_importable is False
    assert find(models, "partial").price_conditions
    assert find(models, "unknown").price is None
    assert next(m for m in models if m.provider == "anthropic").price_importable is True


def test_quote_snapshot_keeps_extra_cost_without_enabling_active_price():
    complex_model = find(catalog(), "cheap-complex")
    snapshot = complex_model.quote_snapshot
    assert snapshot is not None
    assert snapshot.provider == "relay" and snapshot.model_id == "cheap-complex"
    assert snapshot.currency == "USD" and snapshot.unit == 1000000
    assert snapshot.raw_cost["input"] == "0.000000000001"
    assert snapshot.raw_cost["unrecognized_dimension"] == {"amount": "0.000000000002"}
    assert snapshot.raw_cost["cache_write"] == "0.25"
    assert not complex_model.price_importable
    states = {item.key: item.status for item in complex_model.quote_items}
    assert states["input"] == "compatible"
    assert states["cache_write"] == "needs_details"
    assert states["tiers"] == "reference_only"
    assert states["unrecognized_dimension"] == "reference_only"


def test_bad_quote_item_does_not_drop_model_or_other_rates():
    source = {
        "provider": {
            "name": "Provider",
            "models": {
                "valid": {"name": "Valid", "cost": {"input": 0, "output": None, "bad": "x" * 500}},
                "metadata-only": {"name": "Metadata", "cost": {"bad": [0] * 300}},
            },
        }
    }
    models, skipped = reference.parse_catalog(json.dumps(source).encode())
    assert skipped == 0 and len(models) == 2
    valid = find(models, "valid")
    assert valid.quote_snapshot is not None
    assert valid.quote_snapshot.raw_cost["input"] == "0"
    assert valid.quote_snapshot.raw_cost["output"] is None
    assert "bad" not in valid.quote_snapshot.raw_cost
    assert next(item for item in valid.quote_items if item.key == "bad").status == "invalid"
    assert find(models, "metadata-only").quote_snapshot is None


def test_filters_keep_unknown_distinct_and_use_stable_ids():
    models = catalog()
    assert [m.model_id for m in reference.select_models(models, tools="unknown")] == ["partial"]
    assert {m.model_id for m in reference.select_models(models, tools="unsupported")} == {
        "cheap-complex",
        "unknown",
    }
    assert [
        m.provider for m in reference.select_models(models, structured_output="unsupported")
    ] == ["anthropic"]
    assert [m.provider for m in reference.select_models(models, reasoning="supported")] == [
        "anthropic"
    ]
    assert {m.provider for m in reference.select_models(models, developer="anthropic")} == {
        "anthropic",
        "relay",
    }
    assert {
        m.model_id for m in reference.select_models(models, provider="relay", status="alpha")
    } == {"cheap-complex"}
    assert {m.model_id for m in reference.select_models(models, status="exclude_deprecated")} == {
        "claude-v",
        "cheap-complex",
        "unknown",
    }
    assert [m.model_id for m in reference.select_models(models, input_modality="image")] == [
        "claude-v"
    ]
    assert [m.provider for m in reference.select_models(models, output_modality="text")] == [
        "anthropic"
    ]
    assert [m.model_id for m in reference.select_models(models, min_context=150000)] == ["claude-v"]
    assert len(reference.select_models(models, price="available")) == 4
    assert len(reference.select_models(models, price="importable")) == 2
    assert [m.model_id for m in reference.select_models(models, status="deprecated")] == ["partial"]


def test_relevance_price_release_sort_and_full_cache_facets_on_page():
    models = catalog()
    ranked = reference.select_models(
        models, q="claude-v", preferred_provider="relay", preferred_model="claude-v"
    )
    assert [(m.provider, m.model_id) for m in ranked] == [
        ("relay", "claude-v"),
        ("anthropic", "claude-v"),
    ]
    priced = reference.select_models(models, sort="input_price")
    assert [(m.provider, m.model_id) for m in priced[:2]] == [
        ("relay", "claude-v"),
        ("anthropic", "claude-v"),
    ]
    assert [m.model_id for m in priced[2:]] == ["cheap-complex", "partial", "unknown"]
    assert reference.select_models(models, sort="output_price")[0].provider == "relay"
    assert reference.select_models(models, sort="released")[0].model_id == "cheap-complex"
    assert reference.select_models(models, sort="context")[0].provider == "anthropic"
    page = reference.page_models(
        priced,
        models,
        page=2,
        page_size=2,
        fetched_at=datetime.now(UTC),
        stale=False,
        skipped=0,
    )
    assert page.total == 5 and page.page_size == 2
    assert [m.model_id for m in page.items] == ["cheap-complex", "partial"]
    assert [(f.id, f.name) for f in page.facets.providers] == [
        ("anthropic", "Anthropic"),
        ("relay", "Relay"),
    ]
    assert [(f.id, f.name) for f in page.facets.developers] == [("anthropic", "Anthropic")]
