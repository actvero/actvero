"""Single-send transcription via the pinned SDK and isolated multipart transport."""

import asyncio
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.modules.desktop.errors import fail
from app.modules.llm.audio_schemas import (
    TranscriptionInput,
    TranscriptionOptions,
    TranscriptSegment,
)
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.providers.connection import OperationTarget
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk import litellm
from app.modules.llm.providers.sdk_runtime import arguments, session


def prepare(body: TranscriptionInput, options: TranscriptionOptions) -> None:
    if body.duration_ms > options.max_duration_seconds * 1000:
        fail(422, "audio_too_long", "音频超过模型时长上限")
    if body.response_format == "verbose_json" and not options.timestamps:
        fail(422, "timestamps_unavailable", "此模型未启用分段时间戳")


async def generate(
    body: TranscriptionInput,
    upstream_id: str,
    base: str,
    key: str | None,
    timeout: float,
    settings: Settings,
    *,
    target: OperationTarget | None = None,
    trace: AttemptTrace | None = None,
) -> dict[str, Any]:
    if target is not None and target.operation != "transcription":
        raise ValueError("转写目标操作不匹配")
    sdk_base = target.sdk_api_base if target else base
    url = target.url if target else base.rstrip("/") + "/audio/transcriptions"
    expected = target.sdk_expected_url if target else url
    async with session(
        "openai", sdk_base, key, timeout, settings, endpoint=(expected, url), trace=trace
    ) as (
        transport,
        client,
    ):
        async with asyncio.timeout(timeout):
            response = await litellm.atranscription(
                **arguments(
                    "openai",
                    sdk_base,
                    key,
                    timeout,
                    client,
                    {
                        "model": "openai/" + upstream_id,
                        "file": ("audio.wav", body.audio, "audio/wav"),
                        "response_format": body.response_format,
                        **({"language": body.language} if body.language else {}),
                        **(
                            {"timestamp_granularities": ["segment"]}
                            if body.response_format == "verbose_json"
                            else {}
                        ),
                    },
                )
            )
            raw = response.model_dump(exclude_none=True)
            text = raw.get("text")
            if not isinstance(text, str) or len(text) > 100000:
                raise UpstreamFailure(
                    502,
                    "transcript_invalid",
                    "上游未返回有效转写结果",
                    uncertain=True,
                    health_failure=False,
                )
            segments = None
            if body.response_format == "verbose_json":
                try:
                    items = raw.get("segments")
                    if not isinstance(items, list) or len(items) > 2000:
                        raise ValueError("Missing segments")
                    segments = [TranscriptSegment.model_validate(item) for item in items]
                    if any(
                        s.end < s.start or s.end > body.duration_ms / 1000 + 1 for s in segments
                    ):
                        raise ValueError("Invalid timestamps")
                except (ValidationError, ValueError):
                    raise UpstreamFailure(
                        502,
                        "transcript_invalid",
                        "上游分段时间戳无效",
                        uncertain=True,
                        health_failure=False,
                    ) from None
            # Never use LiteLLM's synthesized duration/cost or hidden usage fields.
            usage: dict[str, Any] = {"supplier_usage_source": "unknown"}
            supplied = (transport.response_body or {}).get("usage")
            if isinstance(supplied, dict):
                original = {
                    k: v
                    for k, v in supplied.items()
                    if k in ("input_tokens", "output_tokens", "total_tokens", "seconds")
                    and type(v) is int
                    and 0 <= v <= 1000000000
                }
                if original:
                    usage.update(supplier_usage_source="upstream", supplier_usage=original)
            if trace is not None:
                trace.mark_upstream_terminal()
            return {
                "text": text,
                "segments": [s.model_dump() for s in segments] if segments is not None else None,
                "usage": usage,
            }
