"""Strict operation-specific inputs for one administrator channel diagnostic."""

from __future__ import annotations

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.llm.image_schemas import ImageQuality, ImageSize
from app.modules.llm.schemas import ChannelTestRecord, Input, ProbeText


class DiagnosticInput(Input):
    pass


class DiagnosticChatInput(DiagnosticInput):
    prompt: str = Field(min_length=1, max_length=2000)
    max_output_tokens: int = Field(ge=1, le=512)


class DiagnosticEmbeddingInput(DiagnosticInput):
    input: list[ProbeText] = Field(min_length=1, max_length=8)
    dimensions: int | None = Field(default=None, ge=1, le=65536)


class DiagnosticRerankInput(DiagnosticInput):
    query: ProbeText
    documents: list[ProbeText] = Field(min_length=1, max_length=8)
    top_n: int | None = Field(default=None, ge=1, le=8)

    @model_validator(mode="after")
    def valid_top(self) -> Self:
        if self.top_n is not None and self.top_n > len(self.documents):
            raise ValueError("返回数量不能大于候选文档数量")
        return self


class DiagnosticImageInput(DiagnosticInput):
    prompt: str = Field(min_length=1, max_length=2000)
    size: ImageSize | None = None
    quality: ImageQuality | None = None


class DiagnosticSpeechInput(DiagnosticInput):
    input: str = Field(min_length=1, max_length=1000)
    voice: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,99}$")
    response_format: Literal["wav"] = "wav"


class DiagnosticBase(Input):
    version: int = Field(ge=1)
    request_id: UUID
    upstream_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}$")
    certify_health: bool = False
    model_id: UUID | None = None
    model_version: int | None = Field(default=None, ge=1)
    binding_id: UUID | None = None
    stream: bool = False

    @model_validator(mode="after")
    def explicit_recovery_identity(self) -> Self:
        supplied = (self.model_id, self.model_version, self.binding_id)
        if self.certify_health and any(value is None for value in supplied):
            raise ValueError("验证此绑定需要模型、模型版本和绑定 ID")
        if not self.certify_health and any(value is not None for value in supplied):
            raise ValueError("普通诊断不能附带健康认证身份")
        return self


class ChatDiagnostic(DiagnosticBase):
    operation: Literal["chat"]
    endpoint: Literal["chat_completions"]
    stream: bool = False
    input: DiagnosticChatInput


class EmbeddingDiagnostic(DiagnosticBase):
    operation: Literal["embedding"]
    endpoint: Literal["embeddings"]
    stream: Literal[False] = False
    input: DiagnosticEmbeddingInput


class RerankDiagnostic(DiagnosticBase):
    operation: Literal["rerank"]
    endpoint: Literal["rerank"]
    stream: Literal[False] = False
    input: DiagnosticRerankInput


class ImageDiagnostic(DiagnosticBase):
    operation: Literal["image_generation"]
    endpoint: Literal["images"]
    stream: Literal[False] = False
    input: DiagnosticImageInput


class SpeechDiagnostic(DiagnosticBase):
    operation: Literal["speech"]
    endpoint: Literal["speech"]
    stream: Literal[False] = False
    input: DiagnosticSpeechInput


DiagnosticRequest = Annotated[
    ChatDiagnostic | EmbeddingDiagnostic | RerankDiagnostic | ImageDiagnostic | SpeechDiagnostic,
    Field(discriminator="operation"),
]


class DiagnosticDetail(BaseModel):
    channel_id: UUID
    record: ChannelTestRecord
    media_available: Literal[False] = False
