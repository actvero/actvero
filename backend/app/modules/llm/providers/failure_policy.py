"""Status-only provider rejection policy; never classify from human error text."""

from __future__ import annotations

from app.modules.llm.providers.retrieval import UpstreamFailure


def rejected(
    status: int, *, model_not_found: bool = False, retry_after: int | None = None
) -> UpstreamFailure:
    """Return a safe failure for an explicit upstream HTTP rejection.

    ``model_not_found`` may be true only after a bounded JSON machine-code
    check by the transport. Generic 403/404 errors belong to this binding,
    not the whole credential or every model on its channel.
    """
    binding_failure = status in (403, 404)
    return UpstreamFailure(
        429 if status == 429 else 502,
        "upstream_rate_limited" if status == 429 else "upstream_rejected",
        "上游限流，请稍后重试" if status == 429 else "上游拒绝请求，请检查渠道与模型配置",
        upstream_status=status,
        retryable=status in (401, 403, 404, 429) or status >= 500,
        auth_failure=status == 401,
        health_failure=status == 401 or status >= 500,
        binding_failure=binding_failure,
        binding_failure_reason=(
            "model_unavailable" if model_not_found else "unclassified_rejection"
        )
        if binding_failure
        else None,
        retry_after=retry_after if status == 429 else None,
    )
