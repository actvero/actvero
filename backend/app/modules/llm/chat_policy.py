"""One effective parameter policy for catalog, admission and candidate filtering."""

from typing import Any

from app.modules.desktop.errors import fail
from app.modules.llm.catalog_schemas import CatalogInput, ChatRouteLimits, ModelBinding
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.models import ModelChannel
from app.modules.llm.providers import chat


def resolve(body: ChatInput, config: CatalogInput, version: int) -> ChatInput:
    policy = config.chat_policy
    options = body.actvero
    # A client catalog version is a cache hint, not a reason to reject a
    # request. Apply the current explicit business policy at admission.
    result = body.model_copy(deep=True)
    updates: dict[str, Any] = {}
    for name in ("temperature", "top_p"):
        rule = getattr(policy, name)
        value = getattr(body, name)
        if rule is None:
            continue  # Preserve legacy API behavior; no advertised control without a policy.
        if value is not None and (
            (not rule.adjustable and value != rule.default) or not rule.min <= value <= rule.max
        ):
            fail(422, "parameter_not_allowed", f"{name} 不在允许范围内")
        if value is None and rule.default is not None:
            updates[name] = rule.default
    effort = body.reasoning_effort
    if not policy.reasoning_adjustable and (
        body.thinking is not None or effort not in (None, policy.default_reasoning_effort)
    ):
        fail(422, "parameter_not_allowed", "思考设置由管理员固定")
    if effort is None and body.thinking is None and policy.default_reasoning_effort is not None:
        updates["reasoning_effort"] = policy.default_reasoning_effort
    default_output = policy.default_max_output or config.max_output
    output = body.max_completion_tokens or body.max_tokens or default_output
    if not policy.output_adjustable and output != default_output:
        fail(422, "parameter_not_allowed", "输出上限由管理员固定")
    if body.max_tokens is None and body.max_completion_tokens is None and output:
        updates["max_completion_tokens"] = output
    default_context = policy.default_context_window or config.context_window
    context = (options.context_window if options else None) or default_context
    if (
        context is None
        or config.context_window is None
        or context > config.context_window
        or (not policy.context_adjustable and context != default_context)
    ):
        fail(422, "context_limit_exceeded", "上下文窗口不在允许范围内")
    if output is None or output >= context:
        fail(422, "context_limit_exceeded", "上下文窗口不足以容纳输入与输出")
    result = result.model_copy(update=updates)
    result._context_window = context
    # Reserve the configured model window, not an unverified client estimate.
    # SDK/upstream owns actual context compatibility; bytes are not tokens.
    result._input_reservation = config.context_window
    chat.prepare(result, config, None)
    return result


def route_limits(
    config: CatalogInput, binding: ModelBinding, channel: ModelChannel
) -> ChatRouteLimits:
    explicit = binding.chat_options.limits
    context, output = config.context_window, config.max_output
    parameters = explicit.parameters
    # Catalog metadata is advisory. Only administrator-configured limits can
    # reject a route; provider/model parameter compatibility belongs to the SDK.
    return ChatRouteLimits(
        context_window=min(context, explicit.context_window)
        if context and explicit.context_window
        else explicit.context_window or context,
        max_output=min(output, explicit.max_output)
        if output and explicit.max_output
        else explicit.max_output or output,
        reasoning_efforts=explicit.reasoning_efforts,
        parameters=parameters,
    )


def supports(
    body: ChatInput, config: CatalogInput, binding: ModelBinding, channel: ModelChannel
) -> bool:
    limits = route_limits(config, binding, channel)
    output = body.max_completion_tokens or body.max_tokens or config.max_output or 0
    context = body._context_window or config.context_window or 0
    if limits.context_window and context > limits.context_window:
        return False
    if limits.max_output and output > limits.max_output:
        return False
    if (
        body.reasoning_effort is not None
        and limits.reasoning_efforts is not None
        and body.reasoning_effort not in limits.reasoning_efforts
    ):
        return False
    if limits.parameters is not None and any(
        getattr(body, p) is not None and p not in limits.parameters
        for p in ("temperature", "top_p", "reasoning_effort", "thinking")
    ):
        return False
    return True
