"""Explicit feature declarations from the installed, locked SDK's offline data."""

import json
from functools import lru_cache
from importlib.metadata import distribution
from typing import Any

FIELDS = {
    "tools": "supports_function_calling",
    "structured_output": "supports_response_schema",
    "streaming": "supports_native_streaming",
}
NAMESPACES = {
    "openai": ("openai/", ""),
    "anthropic": ("anthropic/", ""),
    "google": ("gemini/",),
    "google-vertex": ("vertex_ai/",),
    "amazon-bedrock": ("bedrock/",),
    "azure": ("azure/",),
    "deepseek": ("deepseek/",),
    "groq": ("groq/",),
    "mistral": ("mistral/",),
    "xai": ("xai/",),
    "openrouter": ("openrouter/",),
}


@lru_cache(maxsize=1)
def reference() -> dict[str, dict[str, bool]]:
    # Reading package data avoids importing LiteLLM's network-refreshing model map.
    path = distribution("litellm").locate_file(
        "litellm/model_prices_and_context_window_backup.json"
    )
    data = json.loads(path.read_text())
    return {
        name: {key: row[key] for key in FIELDS.values() if isinstance(row.get(key), bool)}
        for name, row in data.items()
        if isinstance(row, dict) and row.get("mode") == "chat"
    }


def features(model: dict[str, Any]) -> dict[str, str]:
    rows = reference()
    keys = [prefix + model["id"] for prefix in NAMESPACES.get(model["provider"], ())]
    matches = [rows[key] for key in keys if key in rows]
    values = {}
    for field, key in FIELDS.items():
        declarations = [row.get(key) for row in matches]
        values[field] = (
            "supported"
            if declarations and all(value is True for value in declarations)
            else "unsupported"
            if declarations and all(value is False for value in declarations)
            else "unknown"
        )
    # The pinned native DSH adapter explicitly implements both features for these entries.
    if model.get("source_version") == "dsh-v0.2.1-rc.2" and model["provider"] == "deepseek":
        for field in ("tools", "streaming"):
            if values[field] == "unknown":
                values[field] = "supported"
    return values


def merge(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Uncertain optional features do not erase a known common chat profile."""
    result = {**profiles[0], "capabilities": dict(profiles[0]["capabilities"])}
    for field in FIELDS:
        values = {p["capabilities"][field] for p in profiles}
        result["capabilities"][field] = values.pop() if len(values) == 1 else "unknown"
    return result


def comparable(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        key: {k: v for k, v in value.items() if k not in FIELDS} if key == "capabilities" else value
        for key, value in profile.items()
        if key != "source"
    }
