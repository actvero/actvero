"""Capability reference for real New API routes; never an upstream model inventory."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from fastapi import Request

from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.model_gateway import ark_capabilities
from app.modules.model_gateway.feature_reference import comparable, features, merge

# Native channel identifiers from the pinned New API channel contract.
PROVIDERS = {
    1: "openai",
    3: "azure",
    14: "anthropic",
    24: "google",
    33: "amazon-bedrock",
    43: "deepseek",
}
LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


@lru_cache(maxsize=1)
def reference() -> list[dict[str, Any]]:
    return cast(
        list[dict[str, Any]],
        json.loads((Path(__file__).parent / "data/model-capabilities.json").read_text())["models"],
    )


def lookup(provider: str | None, model: str) -> dict[str, Any] | None:
    if provider == ark_capabilities.PROVIDER:
        return ark_capabilities.lookup(model)
    candidates = [
        m
        for m in reference()
        if m["id"] == model and (provider is None or m["provider"] == provider)
    ]
    if not candidates and provider is not None:
        # Aggregators often preserve a developer prefix. Match the exact suffix,
        # never substring-match families or guess a future model's abilities.
        candidates = [m for m in reference() if m["id"] == model]
    if not candidates:
        return None
    records = [profile(m) for m in candidates]
    first = records[0]
    if any(comparable(r) != comparable(first) for r in records[1:]):
        return None
    return merge(records)


def profile(model: dict[str, Any]) -> dict[str, Any]:
    levels = []
    if model["reasoning"]:
        mapping = model["thinking"]
        for level in LEVELS:
            key = "off" if level == "none" else level
            if mapping.get(key, "implicit") is None or (
                level in ("xhigh", "max") and key not in mapping
            ):
                continue
            levels.append(level)
    output = min(model["max_output"], max(1, model["context_window"] - 1))
    default = (
        "high"
        if model["provider"] == "deepseek" and "high" in levels
        else "medium"
        if "medium" in levels
        else next(iter(levels), None)
    )
    return {
        "input_modalities": [kind for kind in ("text", "image") if kind in model["input"]],
        "output_modalities": ["text"],
        "context_window": model["context_window"],
        "max_output": output,
        "capabilities": {
            **features(model),
            "vision": "supported" if "image" in model["input"] else "unsupported",
            "reasoning": "supported" if levels else "unsupported",
        },
        "reasoning_options": [{"type": "effort", "values": levels}] if levels else [],
        "chat_policy": {
            "default_max_output": min(8192, output, model["context_window"] // 4),
            "default_reasoning_effort": default,
        },
        "source": {
            "provider": model["provider"],
            "model": model["id"],
            "version": model.get("source_version", "pi-ai@1.1.0"),
        },
    }


def resolve(model: str, group: str, channels: list[dict[str, Any]]) -> dict[str, Any]:
    routes = [
        c
        for c in channels
        if c.get("status") == 1
        and model in (c.get("models") or "").split(",")
        and group in (c.get("group") or "").split(",")
    ]
    profiles = []
    for channel in routes:
        try:
            mapping = channel.get("model_mapping") or {}
            if isinstance(mapping, str):
                mapping = json.loads(mapping)
            upstream = mapping.get(model, model)
        except (ValueError, AttributeError):
            return {"status": "unresolved", "reason": "渠道模型映射无效"}
        resolved = lookup(
            channel.get("capability_provider") or PROVIDERS.get(channel.get("type", 0)), upstream
        )
        if resolved is None:
            return {
                "status": "unresolved",
                "reason": f"尚无 {upstream} 的可靠能力资料，请核对模型映射或更新能力资料",
            }
        profiles.append(resolved)
    if not profiles:
        return {"status": "unresolved", "reason": "尚无适用于当前分组的启用渠道"}
    first = profiles[0]

    if any(comparable(p) != comparable(first) for p in profiles[1:]):
        return {
            "status": "conflict",
            "reason": "此名称映射到能力不同的上游模型，请核对映射或使用不同的模型名称",
        }
    return {"status": "resolved", **merge(profiles)}


async def effective(
    request: Request,
    tenant: UUID,
    config: CatalogInput,
    channels: list[dict[str, Any]] | None = None,
) -> CatalogInput:
    """Use current routes for both discovery and admission, including model aliases."""
    if not config.gateway or config.kind != "chat":
        return config
    if config.gateway.capability_mode == "auto":
        from fastapi import HTTPException

        from app.modules.llm.catalog_schemas import ChatPolicy, ModelCapabilities, ReasoningEffort
        from app.modules.model_gateway import client, service

        connection = await client.relay_connection(request, tenant)
        resolved = resolve(
            config.slug,
            connection.relay_group,
            channels if channels is not None else await service.all_channels(request, tenant),
        )
        if resolved["status"] != "resolved":
            raise HTTPException(409, resolved["reason"])
        config = config.model_copy(
            update={
                "context_window": resolved["context_window"],
                "max_output": resolved["max_output"],
                "capabilities": ModelCapabilities.model_validate(resolved["capabilities"]),
                "reasoning_options": [
                    ReasoningEffort.model_validate(r) for r in resolved["reasoning_options"]
                ],
                "chat_policy": ChatPolicy.model_validate(resolved["chat_policy"]),
                "gateway": config.gateway.model_copy(
                    update={"capability_source": resolved["source"]}
                ),
            }
        )
    # Ark's pass-through route needs a total output bound including reasoning.
    # Other native adapters retain the gateway's universal max_tokens input.
    assert config.gateway is not None
    output_parameter = (
        "max_completion_tokens"
        if config.gateway.capability_source.get("provider") == ark_capabilities.PROVIDER
        else "max_tokens"
    )
    return config.model_copy(
        update={
            "bindings": [
                binding.model_copy(
                    update={
                        "chat_options": binding.chat_options.model_copy(
                            update={"output_parameter": output_parameter}
                        )
                    }
                )
                for binding in config.bindings
            ],
        }
    )
