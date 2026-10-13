"""Pinned LiteLLM SDK setup and compatibility channel Chat diagnostic."""

import asyncio
import os
import time
from collections.abc import Mapping
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.modules.auth.service import now
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.providers.connection import OperationTarget
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.schemas import ChannelTestView

# Process-wide, non-secret startup policy. No remote price fetch or telemetry on import.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
import litellm as litellm  # noqa: E402
from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler  # noqa: E402

litellm.telemetry = False
litellm.suppress_debug_info = True
litellm.turn_off_message_logging = True
# The Router is the sole retry owner. In 1.102.1 OpenAI embedding uses
# `max_retries or litellm.DEFAULT_MAX_RETRIES`, so passing zero alone resets
# the injected client to two retries. Set the process startup default as well;
# never mutate it around concurrent requests.
litellm.num_retries = 0
litellm.DEFAULT_MAX_RETRIES = 0  # type: ignore[attr-defined]


class ChannelHTTPHandler(AsyncHTTPHandler):
    """Version-checked LiteLLM client injection, isolated to one request."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.channel_client = client
        super().__init__(timeout=client.timeout)
        self.client = client

    def create_client(self, *args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return self.channel_client


def token_usage(raw: Mapping[str, Any], adapter: str) -> dict[str, Any]:
    """Keep legacy diagnostic display in native provider counters only."""
    if adapter == "gemini":
        usage = raw
        fields = "promptTokenCount", "candidatesTokenCount"
    elif adapter == "anthropic":
        usage = raw
        fields = "input_tokens", "output_tokens"
    else:
        usage = raw
        fields = "prompt_tokens", "completion_tokens"
    if any(type(usage.get(field)) is not int or usage[field] < 0 for field in fields):
        return {}
    return {
        "usage_source": "upstream",
        "input_tokens": usage[fields[0]],
        "output_tokens": usage[fields[1]],
    }


async def test_chat(
    *,
    adapter: str,
    base: str,
    key: str | None,
    model: str,
    prompt: str,
    max_output: int,
    timeout: int,
    settings: Settings,
    request_id: UUID,
    target: OperationTarget | None = None,
    trace: AttemptTrace | None = None,
) -> ChannelTestView:
    """Use the formal single-attempt Chat transport without member billing."""
    from app.modules.llm.providers import sdk_runtime  # sdk_runtime imports SDK startup settings.

    started = time.monotonic()
    own_trace = trace is None
    trace = trace or AttemptTrace()
    meter_raw: dict[str, Any] = {}
    result: dict[str, Any] = {"ok": False, "message": "调用失败，请检查模型、凭据与接口支持"}
    failure: Exception | None = None
    cancelled = False
    try:
        response = await sdk_runtime.complete(
            adapter,
            base,
            key,
            timeout,
            settings,
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_output,
                "stream": False,
            },
            target=target,
            trace=trace,
            meter_raw=meter_raw,
        )
        output = response["choices"][0]["message"].get("content") or ""
        if not isinstance(output, str):
            raise ValueError("Invalid converted content")
        if key:
            output = output.replace(key, "[已隐藏密钥]")
        result = {"ok": True, "message": "对话测试成功", "output": output[:16000]}
        result.update(token_usage(meter_raw, target.sdk_provider if target else adapter))
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as exc:
        failure = exc
        result["error_code"] = "upstream_error"
        result["uncertain"] = bool(trace.snapshot().get("sent"))
        if isinstance(exc, UpstreamFailure):
            if exc.auth_failure or exc.upstream_status == 401:
                result.update(
                    message="上游拒绝认证，请检查 API Key",
                    error_code="upstream_auth",
                    uncertain=False,
                )
            elif exc.upstream_status == 429:
                result.update(
                    message="上游限流，请稍后重试",
                    error_code="upstream_rate_limit",
                    uncertain=False,
                )
            elif exc.code == "upstream_timeout":
                result.update(
                    message="测试超时，上游可能已受理；请核对后再试",
                    error_code="upstream_timeout",
                )
        elif isinstance(exc, TimeoutError):
            result.update(
                message="测试超时，上游可能已受理；请核对后再试",
                error_code="upstream_timeout",
            )
    finally:
        if own_trace:
            trace.finish(error=failure, cancelled=cancelled)
    return ChannelTestView(
        **result,
        request_id=request_id,
        tested_at=now(),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
