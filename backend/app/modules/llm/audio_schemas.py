"""Bounded speech options and transient audio results."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SpeechOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice: str = Field(default="", pattern=r"^([A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,99})?$")
    response_format: Literal["wav"] = "wav"
    max_input_characters: int = Field(default=1000, ge=1, le=1000, strict=True)


class SpeechInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=200)
    input: str = Field(min_length=1, max_length=1000)
    voice: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,99}$")
    response_format: Literal["wav"] = "wav"


class GeneratedAudio(BaseModel):
    b64_json: str
    media_type: Literal["audio/wav"] = "audio/wav"
    bytes: int
    duration_ms: int
    sample_rate: int
    channels: int


class SpeechOutput(BaseModel):
    id: str
    audio: GeneratedAudio
    usage: dict[str, Any]


class TranscriptionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_duration_seconds: int = Field(default=120, ge=1, le=120, strict=True)
    timestamps: bool = False


class TranscriptionInput(BaseModel):
    """Validated multipart input. The file never enters logs or serialized state."""

    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=200)
    audio: bytes = Field(exclude=True, repr=False)
    duration_ms: int = Field(ge=1, le=120000)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    response_format: Literal["json", "verbose_json"] = "json"


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(strict=True)
    start: float = Field(ge=0, le=121, allow_inf_nan=False)
    end: float = Field(ge=0, le=121, allow_inf_nan=False)
    text: str = Field(max_length=10000)


class TranscriptionOutput(BaseModel):
    id: str
    text: str = Field(max_length=100000)
    segments: list[TranscriptSegment] | None = Field(default=None, max_length=2000)
    usage: dict[str, Any]
