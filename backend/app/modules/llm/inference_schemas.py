"""Bounded text retrieval contracts. Unsupported parameters are rejected explicitly."""

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.desktop.schemas import DesktopErrorDetail
from app.modules.llm.audio_schemas import SpeechOptions, TranscriptionOptions
from app.modules.llm.catalog_schemas import (
    ChatPolicy,
    ChatRouteLimits,
    ModelCapabilities,
    OperationKind,
    ReasoningOption,
    RetrievalOptions,
)
from app.modules.llm.image_schemas import ImageOptions


class InferenceConflictDetail(DesktopErrorDetail):
    call_id: UUID | None = Field(default=None, description="已受理的本人调用标识，不重放生成内容。")
    call_status: str | None = None
    settlement_status: Literal["reserved", "review", "settled", "released"] | None = None


class InferenceConflictResponse(BaseModel):
    error: InferenceConflictDetail


Text = Annotated[str, Field(min_length=1, max_length=200000)]


class InferenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=200)


class EmbeddingInput(InferenceInput):
    input: Text | Annotated[list[Text], Field(min_length=1, max_length=128)]
    dimensions: int | None = Field(default=None, ge=1, le=65536)
    encoding_format: Literal["float"] = "float"


class RerankInput(InferenceInput):
    query: Text
    documents: list[Text] = Field(min_length=1, max_length=128)
    top_n: int | None = Field(default=None, ge=1, le=128)

    @model_validator(mode="after")
    def top_valid(self) -> "RerankInput":
        if self.top_n is not None and self.top_n > len(self.documents):
            raise ValueError("top_n 不能大于文档数量")
        return self


class EmbeddingItem(BaseModel):
    object: Literal["embedding"] = "embedding"
    index: int
    embedding: list[float]


class EmbeddingUsage(BaseModel):
    prompt_tokens: int | None = None
    total_tokens: int | None = None


class EmbeddingOutput(BaseModel):
    object: Literal["list"] = "list"
    model: str
    data: list[EmbeddingItem]
    usage: EmbeddingUsage


class RerankItem(BaseModel):
    index: int
    relevance_score: float


class RerankOutput(BaseModel):
    id: str
    results: list[RerankItem]
    meta: dict[str, Any]


class PublicChatRoute(ChatRouteLimits):
    reasoning_format: Literal["openai", "thinking", "thinking_budget", "enable_thinking"] = "openai"


class PublicOperation(BaseModel):
    chat_policy: ChatPolicy | None = None
    parameter_routes: list[PublicChatRoute] = Field(default_factory=list)
    default_parameters_ready: bool | None = None
    pricing_status: Literal["ready", "no_price", "unconfigured", "currency_mismatch"] = (
        "unconfigured"
    )
    input_modalities: list[Literal["text", "image", "audio"]] = Field(default=["text"])
    output_modalities: list[Literal["text", "vector", "scores", "image", "audio"]] = Field(
        default_factory=list
    )
    kind: OperationKind
    image: ImageOptions | None = None
    speech: SpeechOptions | None = None
    transcription: TranscriptionOptions | None = None
    limits: RetrievalOptions
    capabilities: ModelCapabilities
    context_window: int | None
    max_output: int | None
    reasoning_options: list[ReasoningOption]
    point_rates: dict[str, str | None]
    metric: str
    unit: int = 1000000


class PublicModel(PublicOperation):
    display_order: int = 0
    configuration_version: int = 1
    description: str = ""
    vendor: str = ""
    icon: str = ""
    icon_key: str = ""
    created: int
    owned_by: str = "actvero"
    resource: str
    id: str
    object: Literal["model"] = "model"
    name: str
    operations: list[PublicOperation] = Field(default_factory=list)


class PublicModels(BaseModel):
    object: Literal["list"] = "list"
    data: list[PublicModel]
    has_more: bool
    page: int


class AttemptView(BaseModel):
    attempt_id: UUID | None = None
    evidence_version: int | None = None
    binding_id: UUID | None = None
    operation: str | None = None
    config_version: int | None = None
    sent: bool | None = None
    output_started: bool | None = None
    first_output_ms: int | None = None
    upstream_terminal: bool | None = None
    client_terminal: bool | None = None
    error_scope: str | None = None
    retryable_hint: bool | None = None
    certainly_unused: bool | None = None
    usage_evidence: list[dict[str, Any]] | None = None
    number: int
    channel_id: UUID
    channel_name: str
    upstream_id: str
    channel_version: int
    priority: int
    weight: int
    status: str
    started_at: datetime
    duration_ms: int | None
    error_code: str | None
    upstream_status: int | None
    uncertain: bool
    retry_reason: str | None
    prices: dict[str, Any]
    usage: dict[str, Any]
    estimates: dict[str, Any]


class RouteStateView(BaseModel):
    operation: OperationKind = "chat"
    channel_id: UUID
    upstream_id: str
    state: str
    tested_at: datetime | None
    cooldown_until: datetime | None
    failures: int


class CallView(BaseModel):
    id: UUID
    source: str
    attempts: list[AttemptView] = Field(default_factory=list)
    termination_code: str | None = None
    kind: str
    status: str
    duration_ms: int | None
    error_code: str | None
    usage: dict[str, Any]
    estimates: dict[str, Any]
    created_at: datetime
