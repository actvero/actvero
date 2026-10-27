from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.core.outbound import endpoint
from app.modules.llm.audio_schemas import GeneratedAudio
from app.modules.llm.image_schemas import GeneratedImage, ImageQuality, ImageSize

AddressMode = Literal["provider_default", "service_root", "legacy_api_base"]

if TYPE_CHECKING:
    from app.modules.llm.providers.connection import ChannelConnection

ProviderId = Literal[
    "openai-compatible",
    "openai",
    "anthropic",
    "gemini",
    "deepseek",
    "siliconflow",
    "aihubmix",
    "volcengine",
    "zhipu",
    "moonshot",
    "qwen",
    "qwen-token-plan",
    "aliyun-bailian",
    "volcengine-agent-plan",
    "volcengine-coding-plan",
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ChannelConnectionSettings(Input):
    address_mode: AddressMode
    service_root: str | None = Field(default=None, max_length=2000)
    api_prefix: str | None = Field(default=None, max_length=200)
    legacy_base_url: str | None = Field(default=None, max_length=2000)
    resolver_version: int = Field(default=1, ge=1)

    def resolved(self) -> "ChannelConnection":
        from app.modules.llm.providers.connection import ChannelConnection

        return ChannelConnection(**self.model_dump())


class ProtectionSettings(Input):
    enabled: bool = True


class TestDefaults(Input):
    upstream_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}$")
    operation: Literal["chat", "embedding", "rerank", "image_generation", "speech"]
    endpoint: Literal["chat_completions", "embeddings", "rerank", "images", "speech"]
    stream: bool = False


class TestDefaultsStatus(BaseModel):
    valid: bool
    reason: Literal[
        "ready",
        "model_missing",
        "operation_unsupported",
        "endpoint_unsupported",
        "stream_unsupported",
    ]


HealthSummaryState = Literal[
    "not_applicable", "no_routes", "ready", "degraded", "unavailable", "unverified"
]


class ChannelHealthSummary(BaseModel):
    state: HealthSummaryState
    health_counts: dict[str, int]
    as_of: datetime


class ConnectionInput(Input):
    provider: ProviderId = "openai-compatible"
    base_url: str = Field(default="", max_length=2000)
    connection: ChannelConnectionSettings | None = None
    auth_mode: Literal["api_key", "none"] = "api_key"
    api_key: SecretStr | None = None
    timeout_seconds: int = Field(default=20, ge=3, le=60)
    declared_apis: list[
        Literal[
            "chat_completions",
            "responses",
            "embeddings",
            "rerank",
            "images",
            "speech",
            "transcriptions",
        ]
    ] = Field(default=["chat_completions"], max_length=7)

    @field_validator("base_url")
    @classmethod
    def base(cls, value: str) -> str:
        return endpoint(value).rstrip("/") if value else ""

    @field_validator("api_key")
    @classmethod
    def key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            raw = value.get_secret_value()
            if not 1 <= len(raw) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in raw):
                raise ValueError("API Key 必须是无空白的可打印字符")
        return value

    @model_validator(mode="after")
    def auth(self) -> Self:
        if self.provider != "openai-compatible" and self.auth_mode == "none":
            raise ValueError("此供应商需要 API Key")
        if self.auth_mode == "none" and self.api_key is not None:
            raise ValueError("无认证渠道不能提交 API Key")
        self.declared_apis = list(dict.fromkeys(self.declared_apis))
        return self


class UpstreamModel(Input):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}$")


class ChannelInput(ConnectionInput):
    name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=500)
    icon: str = Field(default="", max_length=350000)
    # Omission preserves inventory for existing callers; [] explicitly clears it.
    models: list[UpstreamModel] | None = Field(default=None, max_length=1000)
    manual_enabled: bool = True
    automatic_protection: ProtectionSettings = Field(default_factory=ProtectionSettings)
    test_defaults: TestDefaults | None = None
    request_id: UUID | None = None


class DraftInspectionInput(ConnectionInput):
    channel_id: UUID | None = None
    version: int | None = Field(default=None, ge=1)
    discover: bool = False

    @model_validator(mode="after")
    def existing_channel(self) -> Self:
        if (self.channel_id is None) != (self.version is None):
            raise ValueError("编辑检查需要同时提供渠道 ID 和版本")
        return self


class ModelDirectory(BaseModel):
    snapshot_id: UUID
    fetched_at: datetime
    candidates: list[UpstreamModel]
    # Older snapshots did not record whether pagination was truncated.
    partial: bool | None = None


class DraftInspectionView(BaseModel):
    ok: bool
    message: str
    checked_at: datetime
    candidates: list[UpstreamModel] = Field(default_factory=list)
    partial: bool = False
    model_directory: ModelDirectory | None = None


class ChannelUpdate(ChannelInput):
    version: int = Field(ge=1)


class Version(Input):
    version: int = Field(ge=1)


class ArchiveInput(Version):
    archived: bool


class RegisteredModel(UpstreamModel):
    source: Literal["manual", "discovery", "configuration"]
    registered_at: datetime


class ModelsInput(Version):
    models: list[UpstreamModel] = Field(min_length=1, max_length=1000)
    snapshot_id: UUID | None = None


class CheckRecord(BaseModel):
    at: datetime
    ok: bool
    message: str
    kind: Literal["check", "discovery"]


class ChannelRemovalReference(BaseModel):
    model_id: UUID
    model_name: str
    operation: str
    binding_id: UUID


class ChannelRemovalConflictDetail(BaseModel):
    code: str
    message: str
    request_id: str
    references: list[ChannelRemovalReference] = Field(default_factory=list)


class ChannelRemovalConflictResponse(BaseModel):
    error: ChannelRemovalConflictDetail


class ChannelBindingReference(ChannelRemovalReference):
    model_version: int | None = None
    upstream_model_id: str
    binding_enabled: bool
    operation_enabled: bool
    model_enabled: bool
    model_archived: bool
    source_registered: bool
    health_state: str
    health_block_reason: str | None = None
    cooldown_until: datetime | None = None
    tested_at: datetime | None = None


class LatestChannelDiagnostic(BaseModel):
    at: datetime
    ok: bool | None
    status: Literal["success", "failure", "unconfirmed"]
    operation: str
    upstream_model_id: str
    request_id: str
    duration_ms: int | None = None
    channel_version: int | None = None
    stale: bool


class ChannelView(BaseModel):
    id: UUID
    version: int
    provider: str
    name: str
    description: str
    icon: str
    base_url: str
    connection: ChannelConnectionSettings
    manual_enabled: bool = True
    automatic_protection: ProtectionSettings = Field(default_factory=ProtectionSettings)
    test_defaults: TestDefaults | None = None
    test_defaults_status: TestDefaultsStatus | None = None
    health_summary: ChannelHealthSummary | None = None
    routing_version: int | None = None
    auth_mode: Literal["api_key", "none"]
    credential_configured: bool
    timeout_seconds: int
    declared_apis: list[str]
    archived: bool
    model_count: int
    last_check: CheckRecord | None
    last_diagnostic: LatestChannelDiagnostic | None = None
    created_at: datetime


class ChannelDetail(ChannelView):
    models: list[RegisteredModel]
    checks: list[CheckRecord]
    model_directory: ModelDirectory | None = None
    binding_references: list[ChannelBindingReference] = Field(default_factory=list)


class ChannelPage(BaseModel):
    items: list[ChannelView]
    total: int


class ChannelStatusInput(Version):
    manual_enabled: bool


class ChannelStatusItem(ChannelStatusInput):
    id: UUID


class ChannelStatusBatch(Input):
    items: list[ChannelStatusItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_items(self) -> Self:
        if len({item.id for item in self.items}) != len(self.items):
            raise ValueError("批量启停不能重复提交同一渠道")
        return self


class ChannelStatusResult(BaseModel):
    id: UUID
    status: Literal["updated", "conflict", "not_found", "archived"]
    version: int | None = None


class ChannelStatusBatchResult(BaseModel):
    items: list[ChannelStatusResult]


class MutationReceiptView(BaseModel):
    scope: Literal["channel.create", "settlement.reconcile"]
    request_id: UUID
    resource_id: UUID
    state: Literal["completed", "pending"]


class ModelHint(BaseModel):
    context_window: int | None = None
    max_output: int | None = None
    supported_parameters: list[str] | None = None
    source: Literal["litellm", "unknown"] = "unknown"
    reference_key: str | None = None
    mode: str | None = None
    kind: (
        Literal["chat", "embedding", "rerank", "image_generation", "speech", "transcription"] | None
    ) = None
    available_kinds: list[
        Literal["chat", "embedding", "rerank", "image_generation", "speech", "transcription"]
    ]


class DiscoveryView(BaseModel):
    channel: ChannelDetail
    ok: bool
    message: str
    snapshot_id: UUID | None = None
    candidates: list[UpstreamModel] = Field(default_factory=list)
    partial: bool = False


class ReferenceCatalog(BaseModel):
    """Reviewed public examples, distinct from authenticated model discovery."""

    models: list[str]
    source_url: str
    checked_at: str


class ProviderView(BaseModel):
    id: ProviderId
    name: str
    model_discovery: bool
    balance_query: bool
    available_for_new_channels: bool = Field(
        default=True,
        description="是否允许新增此供应商渠道；停用新增不影响已有渠道的配置与调用",
    )
    version: int = 1
    category: Literal["vendor", "aggregator", "compatible"] = "compatible"
    icon_key: str = ""
    aliases: list[str] = Field(default_factory=list)
    default_base_url: str = ""
    official_service_root: str = ""
    default_api_prefix: str = ""
    setup_help: str = ""
    reference_catalog: ReferenceCatalog | None = None
    base_url_help: str = "填写接口根地址，保留服务要求的 /v1 等路径。"
    allow_no_auth: bool = False
    default_apis: list[str] = Field(default_factory=lambda: ["chat_completions"])
    # Capability of this platform release, not a blanket SDK support claim.
    member_inference: bool = False
    member_operations: list[
        Literal["chat", "embedding", "rerank", "image_generation", "speech", "transcription"]
    ] = Field(default_factory=list)
    test_operations: list[Literal["chat", "embedding", "rerank", "image_generation", "speech"]] = (
        Field(default=["chat"])
    )


class ChannelTestInput(Version, UpstreamModel):
    prompt: str = Field(min_length=1, max_length=2000)
    max_output_tokens: int = Field(ge=1, le=512)


class ChannelChatProbe(ChannelTestInput):
    operation: Literal["chat"]


ProbeText = Annotated[str, Field(min_length=1, max_length=2000)]


class ChannelEmbeddingProbe(Version, UpstreamModel):
    operation: Literal["embedding"]
    input: list[ProbeText] = Field(min_length=1, max_length=8)
    dimensions: int | None = Field(default=None, ge=1, le=65536)


class ChannelRerankProbe(Version, UpstreamModel):
    operation: Literal["rerank"]
    query: ProbeText
    documents: list[ProbeText] = Field(min_length=1, max_length=8)
    top_n: int | None = Field(default=None, ge=1, le=8)

    @model_validator(mode="after")
    def valid_top(self) -> Self:
        if self.top_n is not None and self.top_n > len(self.documents):
            raise ValueError("返回数量不能大于候选文档数量")
        return self


class ChannelImageProbe(Version, UpstreamModel):
    operation: Literal["image_generation"]
    prompt: str = Field(min_length=1, max_length=2000)
    size: ImageSize | None = None
    quality: ImageQuality | None = None


class ChannelSpeechProbe(Version, UpstreamModel):
    operation: Literal["speech"]
    input: str = Field(min_length=1, max_length=1000)
    voice: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,99}$")
    response_format: Literal["wav"] = "wav"


ChannelProbe = Annotated[
    ChannelChatProbe
    | ChannelEmbeddingProbe
    | ChannelRerankProbe
    | ChannelImageProbe
    | ChannelSpeechProbe,
    Field(discriminator="operation"),
]


class VectorPreview(BaseModel):
    index: int
    dimensions: int
    values: list[float]


class RankPreview(BaseModel):
    index: int
    relevance_score: float


class ChannelTestView(BaseModel):
    stream: bool = False
    health_certification: Literal["not_requested", "certified", "not_certified"] = "not_requested"
    operation: Literal["chat", "embedding", "rerank", "image_generation", "speech"] = "chat"
    ok: bool
    message: str
    request_id: UUID
    tested_at: datetime
    duration_ms: int
    output: str = ""
    usage_source: Literal["upstream", "unknown"] = "unknown"
    input_tokens: int | None = None
    output_tokens: int | None = None
    search_units: int | None = None
    image_count: int | None = None
    audio_duration_ms: int | None = None
    image: GeneratedImage | None = None
    audio: GeneratedAudio | None = None
    vectors: list[VectorPreview] = Field(default_factory=list)
    ranks: list[RankPreview] = Field(default_factory=list)
    error_code: str | None = None
    uncertain: bool = False
    attempt: dict[str, Any] | None = None


class ChannelTestRecord(BaseModel):
    stream: bool | None = None
    health_certification: Literal["not_requested", "certified", "not_certified"] = "not_requested"
    request_id: str
    model: str
    operation: str
    tested_at: datetime
    status: Literal["success", "failure", "unconfirmed"]
    duration_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    search_units: int | None = None
    image_count: int | None = None
    audio_duration_ms: int | None = None
    channel_version: int | None = None
    stale: bool = False
    uncertain: bool = False
    error_code: str | None = None
    record_version: Literal["legacy_audit", "attempt_v1"] = "legacy_audit"
    attempt: dict[str, Any] | None = None
