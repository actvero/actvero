"""LiteLLM retrieval calls with request-local networking and original upstream meters."""

import asyncio
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.modules.llm.providers.connection import OperationTarget
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk import litellm
from app.modules.llm.providers.sdk_runtime import arguments, session

if TYPE_CHECKING:
    from app.modules.llm.providers.attempt import AttemptTrace


async def post(
    base: str,
    path: str,
    key: str | None,
    timeout: float,
    settings: Settings,
    payload: dict[str, Any],
    *,
    target: OperationTarget | None = None,
    trace: "AttemptTrace | None" = None,
) -> dict[str, Any]:
    if path not in ("/embeddings", "/rerank"):
        raise UpstreamFailure(
            422, "unsupported_operation", "不支持此检索操作", health_failure=False
        )
    embedding = path == "/embeddings"
    adapter = "openai" if embedding else "cohere"
    target_url = base.rstrip("/") + path
    # LiteLLM 1.102.1's Cohere adapter insists on /v1/rerank. Preserve existing
    # compatible deployments with arbitrary API prefixes using an exact URL map.
    # Only the path changes; credentials and the pinned origin remain per channel.
    sdk_base = base if embedding else base.rstrip("/") + "/v1/rerank"
    expected = target_url if embedding else sdk_base
    if target is not None:
        if target.operation != ("embedding" if embedding else "rerank"):
            raise ValueError("检索目标操作不匹配")
        adapter, sdk_base = target.sdk_provider, target.sdk_api_base
        expected, target_url = target.sdk_expected_url, target.url
    session_base = sdk_base if target else base
    async with session(
        adapter, session_base, key, timeout, settings, endpoint=(expected, target_url), trace=trace
    ) as (
        transport,
        client,
    ):
        params = arguments(adapter, sdk_base, key, timeout, client, payload)
        async with asyncio.timeout(timeout):
            if embedding:
                # dimensions was already validated against this model's explicit
                # dimension_options; compatible model names need not match OpenAI's.
                response = await litellm.aembedding(**params, allowed_openai_params=["dimensions"])
            else:
                response = await litellm.arerank(**params, return_documents=False)
        # Deliver the SDK-normalized result. Original counters alone substantiate
        # billing; a missing/unreadable meter never replaces the SDK's output.
        result: dict[str, Any] = response.model_dump(exclude_none=True)
        original = transport.response_body or {}
        result["usage"] = original.get("usage")
        result["meta"] = original.get("meta")
        return result
