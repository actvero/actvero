"""Single-attempt LiteLLM image generation with original counters and controlled delivery."""

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.modules.desktop.errors import fail
from app.modules.llm.image_schemas import ImageInput, ImageOptions
from app.modules.llm.providers.connection import OperationTarget
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk import litellm
from app.modules.llm.providers.sdk_runtime import arguments, session
from app.modules.llm.schemas import ChannelImageProbe

if TYPE_CHECKING:
    from app.modules.llm.providers.attempt import AttemptTrace


@dataclass
class ImageResult:
    image: object
    usage: dict[str, int | None]


def prepare(body: ImageInput, options: ImageOptions, upstream_id: str) -> ChannelImageProbe:
    if not body.prompt.strip() or len(body.prompt) > options.max_prompt_characters:
        fail(422, "image_prompt_invalid", "提示词为空或超过模型上限")
    for key in ("size", "quality"):
        if getattr(body, key) is not None and getattr(body, key) != getattr(options, key):
            fail(422, "image_parameter_unavailable", "尺寸或质量与模型配置不符")
    return ChannelImageProbe(
        operation="image_generation",
        version=1,
        id=upstream_id,
        prompt=body.prompt,
        size=options.size,
        quality=options.quality,
    )


def raw_counts(raw: dict[str, Any]) -> dict[str, int | None]:
    usage = raw.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    return {
        name: value if type(value := usage.get(name)) is int and 0 <= value <= 100_000_000 else None
        for name in ("input_tokens", "output_tokens")
    }


async def generate(
    body: ChannelImageProbe,
    base: str,
    key: str | None,
    timeout: float,
    settings: Settings,
    *,
    target: OperationTarget | None = None,
    trace: "AttemptTrace | None" = None,
) -> ImageResult:
    if target is not None and target.operation != "image_generation":
        raise ValueError("图片目标操作不匹配")
    sdk_base = target.sdk_api_base if target else base
    target_url = target.url if target else base.rstrip("/") + "/images/generations"
    expected = target.sdk_expected_url if target else target_url
    async with session(
        "openai", sdk_base, key, timeout, settings, endpoint=(expected, target_url), trace=trace
    ) as (
        transport,
        client,
    ):
        payload = {"model": "openai/" + body.id, "prompt": body.prompt, "n": 1}
        payload.update(body.model_dump(include={"size", "quality"}, exclude_none=True))
        async with asyncio.timeout(timeout):
            response = await litellm.aimage_generation(
                **arguments("openai", sdk_base, key, timeout, client, payload)
            )
        raw = transport.response_body
        data = response.model_dump(exclude_none=True).get("data")
        if not isinstance(data, list) or len(data) != 1:
            raise UpstreamFailure(
                502,
                "image_delivery_failed",
                "本接口需要单张图片结果",
                uncertain=True,
                health_failure=False,
            )
        if trace is not None:
            trace.mark_upstream_terminal()
            trace.observe_usage({"source": "upstream", **raw_counts(raw or {})})
    # Never send channel credentials to the image host. A failed download must not
    # trigger another billable generation. No SDK-derived meters or prices are used.
    return ImageResult(image=data[0], usage=raw_counts(raw or {}))
