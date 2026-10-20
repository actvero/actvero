"""Reject ambiguous monetary observations without rejecting SDK model output."""

import pytest
from test_settlement_evidence import attempt, evidence, price

from app.modules.llm.providers import chat
from app.modules.llm.providers.sdk_meter import Meter
from app.modules.llm.settlement_evidence import evaluate


@pytest.mark.parametrize(
    "extra",
    [
        {"cache_creation_input_tokens": 20, "cache_creation_5m_input_tokens": 5},
        {"cache_creation_input_tokens": 0, "cache_creation_1h_input_tokens": 5},
        {"cache_creation_input_tokens": -1, "cache_creation_5m_input_tokens": 5},
        {"cache_creation_input_tokens": True, "cache_creation_5m_input_tokens": 5},
        {"prompt_cache_hit_tokens": 10, "prompt_tokens_details": {"cached_tokens": 20}},
        {"total_tokens": 101},
    ],
)
def test_conflicting_openai_counts_cannot_create_a_bill(extra):
    raw = {"prompt_tokens": 100, "completion_tokens": 10, **extra}
    assert chat.usage(raw)["source"] == "unknown"
    observed = []
    meter = Meter("openai", lambda usage, terminal: observed.append((usage, terminal)))
    meter.observe({"usage": raw, "choices": [{"finish_reason": "stop"}]}, stream=False)
    fields = [evidence(k, v) for k, v in observed[-1][0].items() if k != "source"]
    result = evaluate(
        price(output="2", cache_read="0.1", cache_write_5m="1.2", cache_write_1h="2"),
        [attempt(fields=fields)],
        delivered=True,
    )
    assert result.action == "review"


def test_matching_aliases_and_cache_totals_remain_billable():
    raw = {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "total_tokens": 110,
        "prompt_cache_hit_tokens": 20,
        "prompt_tokens_details": {"cached_tokens": 20},
        "cache_creation_input_tokens": 8,
        "cache_creation_5m_input_tokens": 3,
        "cache_creation_1h_input_tokens": 5,
    }
    assert chat.usage(raw) == {
        "source": "upstream",
        "input_tokens": 72,
        "output_tokens": 10,
        "cache_read_tokens": 20,
        "cache_write_5m_tokens": 3,
        "cache_write_1h_tokens": 5,
    }
