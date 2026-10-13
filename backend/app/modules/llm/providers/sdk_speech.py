"""Single-send LiteLLM TTS using the existing isolated outbound client."""

import asyncio
from typing import TYPE_CHECKING

from app.core.config import Settings
from app.modules.desktop.errors import fail
from app.modules.llm.audio_delivery import deliver_audio
from app.modules.llm.audio_schemas import GeneratedAudio, SpeechInput, SpeechOptions
from app.modules.llm.providers.connection import OperationTarget
from app.modules.llm.providers.sdk import litellm
from app.modules.llm.providers.sdk_runtime import arguments, session
from app.modules.llm.schemas import ChannelSpeechProbe

if TYPE_CHECKING:
    from app.modules.llm.providers.attempt import AttemptTrace


def prepare(body: SpeechInput, options: SpeechOptions, upstream_id: str) -> ChannelSpeechProbe:
    if not body.input.strip() or len(body.input) > options.max_input_characters:
        fail(422, "speech_input_invalid", "朗读文本为空或超过模型上限")
    if not options.voice:
        fail(409, "speech_voice_missing", "请先配置模型音色")
    if body.voice is not None and body.voice != options.voice:
        fail(422, "speech_voice_unavailable", "音色与模型配置不符")
    return ChannelSpeechProbe(
        operation="speech", version=1, id=upstream_id, input=body.input, voice=options.voice
    )


async def generate(
    body: ChannelSpeechProbe,
    base: str,
    key: str | None,
    timeout: float,
    settings: Settings,
    *,
    target: OperationTarget | None = None,
    trace: "AttemptTrace | None" = None,
) -> GeneratedAudio:
    if target is not None and target.operation != "speech":
        raise ValueError("语音目标操作不匹配")
    sdk_base = target.sdk_api_base if target else base
    target_url = target.url if target else base.rstrip("/") + "/audio/speech"
    expected = target.sdk_expected_url if target else target_url
    async with session(
        "openai",
        sdk_base,
        key,
        timeout,
        settings,
        endpoint=(expected, target_url),
        binary_audio=True,
        trace=trace,
    ) as (transport, client):
        async with asyncio.timeout(timeout):
            response = await litellm.aspeech(
                **arguments(
                    "openai",
                    sdk_base,
                    key,
                    timeout,
                    client,
                    {
                        "model": "openai/" + body.id,
                        "input": body.input,
                        "voice": body.voice,
                        "response_format": "wav",
                    },
                )
            )
            # Ignore SDK estimates and headers: audio duration is media metadata,
            # not an authenticated supplier usage report.
            audio = deliver_audio(response.content)
            if trace is not None:
                trace.mark_upstream_terminal()
            return audio
