"""Validate complete bounded PCM WAV and strip ancillary metadata before delivery."""

import base64
import wave
from io import BytesIO

from app.modules.llm.audio_schemas import GeneratedAudio
from app.modules.llm.providers.retrieval import UpstreamFailure

MAX_AUDIO_BYTES = 8_000_000


def deliver_audio(content: bytes) -> GeneratedAudio:
    try:
        if not 44 <= len(content) <= MAX_AUDIO_BYTES:
            raise ValueError("Audio size")
        # An incomplete declared RIFF is not proof of a delivered recording.
        if content[:4] != b"RIFF" or int.from_bytes(content[4:8], "little") + 8 != len(content):
            raise ValueError("Incomplete RIFF")
        with wave.open(BytesIO(content), "rb") as source:
            rate, channels, width, frames = (
                source.getframerate(),
                source.getnchannels(),
                source.getsampwidth(),
                source.getnframes(),
            )
            if (
                source.getcomptype() != "NONE"
                or channels not in (1, 2)
                or width not in (1, 2, 3, 4)
                or not 8000 <= rate <= 96000
                or not 0 < frames <= rate * 120
                or frames * channels * width > MAX_AUDIO_BYTES - 44
            ):
                raise ValueError("Unsupported WAV")
            samples = source.readframes(frames)
            if len(samples) != frames * channels * width:
                raise ValueError("Truncated WAV")
        output = BytesIO()
        with wave.open(output, "wb") as target:
            target.setnchannels(channels)
            target.setsampwidth(width)
            target.setframerate(rate)
            target.writeframes(samples)
        normalized = output.getvalue()
        return GeneratedAudio(
            b64_json=base64.b64encode(normalized).decode("ascii"),
            bytes=len(normalized),
            duration_ms=max(1, frames * 1000 // rate),
            sample_rate=rate,
            channels=channels,
        )
    except (ValueError, wave.Error, EOFError, OverflowError):
        raise UpstreamFailure(
            502,
            "audio_delivery_failed",
            "上游音频不是完整的 PCM WAV，或超过 8 MB / 120 秒",
            uncertain=True,
            health_failure=False,
        ) from None
