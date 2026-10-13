"""LiteLLM chat conversion; Actvero owns authorization, attempts and settlement."""

import asyncio
import base64
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import anyio
import httpx
import httpx2
from fastapi import HTTPException
from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.outbound import PinnedTransport, resolve
from app.modules.llm.providers import chat
from app.modules.llm.providers.connection import OperationTarget
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk import ChannelHTTPHandler, litellm
from app.modules.llm.providers.sdk_meter import Meter
from app.modules.llm.providers.sdk_transport import RuntimeTransport

if TYPE_CHECKING:
    from app.modules.llm.providers.attempt import AttemptTrace


def selected_usage(meter: Meter) -> dict[str, Any]:
    """Accounting observes original counters; SDK estimates are not billable evidence."""
    if meter.observation_error is not None:
        return {"source": "unknown"}
    return meter.usage()


async def prepare_images(payload: dict[str, Any], settings: Settings) -> None:
    """Native SDK converters must never fetch user URLs via an unvalidated client."""
    downloaded = 0
    for message in payload["messages"]:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if part.get("type") != "image_url":
                continue
            url = part["image_url"]["url"]
            if url.startswith("data:"):
                continue
            transport = PinnedTransport(
                url,
                lambda target: resolve(target, [], dns=settings.llm_public_dns),
                max_bytes=min(5_000_000, 8_000_000 - downloaded),
            )
            try:
                async with httpx2.AsyncClient(
                    transport=transport, trust_env=False, follow_redirects=False, timeout=10
                ) as client:
                    async with client.stream(
                        "GET", url, headers={"accept-encoding": "identity"}
                    ) as response:
                        mime = (
                            response.headers.get("content-type", "").split(";")[0].strip().lower()
                        )
                        if (
                            response.status_code != 200
                            or response.headers.get("content-encoding", "identity").lower()
                            != "identity"
                            or mime not in ("image/png", "image/jpeg", "image/webp", "image/gif")
                        ):
                            raise ValueError("Invalid image response")
                        content_bytes = await response.aread()
                        downloaded += len(content_bytes)
                encoded = base64.b64encode(content_bytes).decode("ascii")
                part["image_url"]["url"] = f"data:{mime};base64,{encoded}"
            except Exception:
                raise UpstreamFailure(
                    422,
                    "image_unavailable",
                    "无法安全读取图片，请使用公开图片地址或 data URL",
                    health_failure=False,
                ) from None


@asynccontextmanager
async def session(
    adapter: str,
    base: str,
    key: str | None,
    timeout: float,
    settings: Settings,
    *,
    endpoint: tuple[str, str] | None = None,
    binary_audio: bool = False,
    trace: "AttemptTrace | None" = None,
) -> AsyncGenerator[tuple[RuntimeTransport, Any]]:
    transport = RuntimeTransport(
        base, key, settings, adapter, endpoint=endpoint, binary_audio=binary_audio, trace=trace
    )
    http = httpx.AsyncClient(
        transport=transport,
        trust_env=False,
        follow_redirects=False,
        timeout=timeout,
    )
    client: Any = (
        AsyncOpenAI(api_key=key or "unused-no-auth", base_url=base, http_client=http, max_retries=0)
        if adapter == "openai"
        else ChannelHTTPHandler(http)
    )
    try:
        yield transport, client
    except (asyncio.CancelledError, GeneratorExit):
        if trace is not None:
            trace.finish(cancelled=True)
        raise
    except Exception as exc:
        if transport.failure is not None:
            if trace is not None:
                trace.note_error(transport.failure)
            raise transport.failure from None
        if isinstance(exc, HTTPException):
            if trace is not None:
                trace.note_error(exc)
            raise
        if isinstance(exc, TimeoutError):
            failure = UpstreamFailure(
                504,
                "upstream_timeout",
                "上游请求超时，执行结果未确认",
                retryable=True,
                uncertain=transport.sent,
            )
            if trace is not None:
                trace.note_error(failure)
            raise failure from None
        failure = UpstreamFailure(
            502 if transport.sent else 422,
            "sdk_response_error" if transport.sent else "unsupported_sdk_parameters",
            "SDK 未能完成响应处理" if transport.sent else "该供应商或模型不支持此请求参数",
            uncertain=transport.sent,
            health_failure=False,
        )
        if trace is not None:
            trace.note_error(failure)
        raise failure from None
    finally:
        with anyio.move_on_after(3, shield=True):
            await http.aclose()


def arguments(
    adapter: str,
    base: str,
    key: str | None,
    timeout: float,
    client: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        **payload,
        "custom_llm_provider": adapter,
        "api_base": base,
        "api_key": key or "unused-no-auth",
        "client": client,
        "timeout": timeout,
        "num_retries": 0,
        "max_retries": 0,
        "caching": False,
        "drop_params": False,
    }


async def complete(
    adapter: str,
    base: str,
    key: str | None,
    timeout: float,
    settings: Settings,
    payload: dict[str, Any],
    *,
    target: OperationTarget | None = None,
    trace: "AttemptTrace | None" = None,
    meter_usage: dict[str, Any] | None = None,
    meter_raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if target is not None:
        if target.operation != "chat":
            raise ValueError("对话目标操作不匹配")
        adapter, base = target.sdk_provider, target.sdk_api_base
    endpoint = (target.sdk_expected_url, target.url) if target else None
    async with session(adapter, base, key, timeout, settings, endpoint=endpoint, trace=trace) as (
        transport,
        client,
    ):
        async with asyncio.timeout(timeout):
            await prepare_images(payload, settings)
            response = await litellm.acompletion(
                **arguments(adapter, base, key, timeout, client, payload)
            )
        raw: dict[str, Any] = response.model_dump(exclude_none=True)
        usage = selected_usage(transport.meter)
        # Preserve SDK choices and metadata. Only usage has a platform provenance rule.
        raw["usage"] = transport.meter.openai_usage() if usage.get("source") == "upstream" else None
        if meter_usage is not None:
            meter_usage.update(usage)
        if meter_raw is not None and isinstance(transport.meter.raw, dict):
            meter_raw.update(transport.meter.raw)
        if trace is not None:
            trace.mark_upstream_terminal()
        return raw


async def events(
    adapter: str,
    base: str,
    key: str | None,
    timeout: float,
    settings: Settings,
    payload: dict[str, Any],
    model: str,
    request_id: str,
    state: chat.StreamState,
    *,
    target: OperationTarget | None = None,
    trace: "AttemptTrace | None" = None,
) -> AsyncGenerator[dict[str, Any]]:
    if target is not None:
        if target.operation != "chat":
            raise ValueError("对话目标操作不匹配")
        adapter, base = target.sdk_provider, target.sdk_api_base
    endpoint = (target.sdk_expected_url, target.url) if target else None
    async with session(adapter, base, key, timeout, settings, endpoint=endpoint, trace=trace) as (
        transport,
        client,
    ):
        stream = None
        deadline = time.monotonic() + timeout
        try:
            async with asyncio.timeout(timeout):
                await prepare_images(payload, settings)
                stream = await litellm.acompletion(
                    **arguments(adapter, base, key, timeout, client, payload)
                )
            # Do not hold a timeout context across yield: StreamingResponse changes tasks
            # after preflight. Each await uses the same absolute request deadline.
            while True:
                try:
                    async with asyncio.timeout(max(0, deadline - time.monotonic())):
                        chunk = await anext(stream)
                except StopAsyncIteration:
                    break
                raw = chunk.model_dump(exclude_none=True)
                state.usage = selected_usage(transport.meter)
                # LiteLLM's final usage chunk can contain a default empty choice.
                meter_only = "usage" in raw and not any(
                    choice.get("finish_reason") or any(choice.get("delta", {}).values())
                    for choice in raw.get("choices", [])
                )
                raw.pop("usage", None)  # The SDK can synthesize usage; only raw counters settle.
                if meter_only:
                    continue
                output = state.chunk(raw, model, request_id)
                if output is not None:
                    delta = output["choices"][0]["delta"]
                    if trace is not None and any(
                        delta.get(key)
                        for key in ("content", "reasoning_content", "refusal", "tool_calls")
                    ):
                        trace.mark_output()
                    yield output
            # SDK iteration owns completion. Raw termination is accounting evidence,
            # not another condition that can interrupt an otherwise accepted response.
        finally:
            state.usage = selected_usage(transport.meter)
            if stream is not None and hasattr(stream, "aclose"):
                with anyio.move_on_after(3, shield=True):
                    await stream.aclose()
