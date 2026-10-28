"""Reviewed Ark Plan profiles, scoped to the exact native connection template."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PROVIDER = "volcengine-ark-plan"


@lru_cache(maxsize=1)
def reference() -> dict[str, Any]:
    catalog: dict[str, Any] = json.loads(
        (Path(__file__).parent / "data/ark-plan-capabilities.json").read_text()
    )
    return catalog


def lookup(model: str) -> dict[str, Any] | None:
    catalog = reference()
    entry = catalog["models"].get(model)
    if entry is None:
        return None
    output = min(entry["max_output"], entry["context_window"] - 1)
    efforts = entry["efforts"]
    return {
        "input_modalities": entry["input"],
        "output_modalities": ["text"],
        "context_window": entry["context_window"],
        "max_output": output,
        "capabilities": {
            "tools": entry.get("tools", "unknown"),
            "streaming": "supported",
            "structured_output": entry.get("structured_output", "unknown"),
            "vision": entry.get(
                "vision", "supported" if "image" in entry["input"] else "unsupported"
            ),
            "reasoning": "supported",
        },
        "reasoning_options": [{"type": "effort", "values": efforts}],
        "chat_policy": {
            "default_max_output": min(8192, output, entry["context_window"] // 4),
            "default_reasoning_effort": entry.get("default_effort"),
            "reasoning_adjustable": efforts != [None],
        },
        "source": {
            "provider": PROVIDER,
            "model": model,
            "version": catalog["version"],
            "verified_at": catalog["verified_at"],
            "url": catalog["sources"][entry["sources"][0]],
            "references": " ".join(catalog["sources"][key] for key in entry["sources"]),
            "source_model": entry.get("source_model", model),
        },
    }
