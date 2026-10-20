"""Platform chat input validation and public response contract; SDK handles protocols."""

from typing import Any

from app.modules.desktop.errors import fail
from app.modules.llm.catalog_schemas import (
    CatalogInput,
    ModelBinding,
    effective_reasoning_format,
)
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.providers.retrieval import count


def prepare(
    body: ChatInput, config: CatalogInput, binding: ModelBinding | None, adapter: str = "openai"
) -> dict[str, Any]:
    maximum = body.max_completion_tokens or body.max_tokens or config.max_output
    if maximum is None or config.max_output is None or maximum > config.max_output:
        fail(422, "output_limit_required", "请配置模型最大输出，调用上限不得超过该值")
    # Capabilities/reasoning options describe the model for the UI. They are not
    # another provider validator. Explicit platform policy is applied in resolve().
    payload = body.model_dump(
        exclude_none=True,
        exclude={"stream_options", "max_tokens", "max_completion_tokens", "actvero"},
    )
    if binding:
        payload["model"] = binding.upstream_id
        payload[binding.chat_options.output_parameter] = maximum
        # Native parameter mapping belongs to LiteLLM, not OpenAI-compatible dialect rules.
        dialect = (
            effective_reasoning_format(
                binding.chat_options.reasoning_format,
                config.reasoning_options,
            )
            if adapter == "openai"
            else "thinking_budget"
        )
        if body.thinking and dialect == "enable_thinking":
            payload["extra_body"] = {"enable_thinking": body.thinking.type == "enabled"}
            if body.thinking.budget_tokens is None:
                payload.pop("thinking", None)
        elif (
            body.thinking
            and dialect == "openai"
            and body.thinking.type == "disabled"
            and body.thinking.budget_tokens is None
            and body.reasoning_effort is None
        ):
            payload.pop("thinking", None)
            payload["reasoning_effort"] = "none"
        # Preserve remaining requested options for SDK validation/conversion.
        # Never guess compatibility or silently discard a budget/effort.
    if body.stream:
        payload["stream_options"] = {"include_usage": True}
    return payload


def usage(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"source": "unknown"}
    total = count(raw.get("prompt_tokens"))
    output = count(raw.get("completion_tokens"))
    if total is None or output is None:
        return {"source": "unknown"}
    details = raw.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        return {"source": "unknown"}
    cache = count(raw.get("prompt_cache_hit_tokens", details.get("cached_tokens", 0)))
    write5 = count(raw.get("cache_creation_5m_input_tokens", 0))
    write1 = count(raw.get("cache_creation_1h_input_tokens", 0))
    if cache is None or write5 is None or write1 is None or cache + write5 + write1 > total:
        return {"source": "unknown"}
    # Aliases and optional totals must agree. These checks affect monetary
    # evidence only: LiteLLM still owns response delivery and protocol parsing.
    if (
        "prompt_cache_hit_tokens" in raw
        and "cached_tokens" in details
        and count(details["cached_tokens"]) != cache
    ):
        return {"source": "unknown"}
    if "total_tokens" in raw and count(raw["total_tokens"]) != total + output:
        return {"source": "unknown"}
    # A partially split cache-write total is as ambiguous as an unsplit total.
    if (
        "cache_creation_input_tokens" in raw
        and count(raw["cache_creation_input_tokens"]) != write5 + write1
    ):
        return {"source": "unknown"}
    return {
        "source": "upstream",
        "input_tokens": total - cache - write5 - write1,
        "output_tokens": output,
        "cache_read_tokens": cache,
        "cache_write_5m_tokens": write5,
        "cache_write_1h_tokens": write1,
    }


def public_usage(meter: dict[str, Any]) -> dict[str, Any] | None:
    if meter.get("source") != "upstream":
        return None
    prompt = sum(
        meter[k + "_tokens"] for k in ("input", "cache_read", "cache_write_5m", "cache_write_1h")
    )
    return {
        "prompt_tokens": prompt,
        "completion_tokens": meter["output_tokens"],
        "total_tokens": prompt + meter["output_tokens"],
        "prompt_tokens_details": {"cached_tokens": meter["cache_read_tokens"]},
    }


def normalize(
    raw: dict[str, Any], body: ChatInput, request_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Add platform identity to the SDK response without reinterpreting its choices."""
    return {
        **raw,
        "id": "chatcmpl-" + request_id,
        "model": body.model,
    }, usage(raw.get("usage"))


class StreamState:
    """Observe SDK lifecycle metadata; never rebuild or validate model output."""

    def __init__(self) -> None:
        self.usage: dict[str, Any] = {"source": "unknown"}
        self.finished = False

    def chunk(self, raw: dict[str, Any], model: str, request_id: str) -> dict[str, Any] | None:
        choices = raw.get("choices") or []
        if any(choice.get("finish_reason") is not None for choice in choices):
            self.finished = True
        if not choices:
            return None  # Usage is observed independently and emitted by the caller.
        return {
            **raw,
            "id": "chatcmpl-" + request_id,
            "model": model,
        }
