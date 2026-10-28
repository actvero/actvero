import re
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from app.modules.llm.audio_schemas import SpeechOptions, TranscriptionOptions
from app.modules.llm.image_schemas import ImageOptions
from app.modules.llm.model_identifier import ModelIdentifier
from app.modules.llm.reference_quotes import QuoteSnapshot
from app.modules.llm.schemas import Input

RATE_FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
Rate = Annotated[Decimal, Field(ge=0, le=1000000000, max_digits=27, decimal_places=15)]
Currency = Literal["USD", "CNY", "EUR", "GBP", "JPY", "HKD"]
OperationKind = Literal[
    "chat", "embedding", "rerank", "image_generation", "speech", "transcription"
]
Declaration = Literal["unknown", "supported", "unsupported"]
Effort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max", "default"]


class PointConversionInput(Input):
    version: int = Field(ge=0, strict=True)
    currency: Currency
    points_per_currency: str = Field(
        pattern=r"^(0|[1-9][0-9]{0,12})(\.[0-9]{1,12})?$", max_length=26
    )

    @field_validator("points_per_currency")
    @classmethod
    def positive_ratio(cls, value: str) -> str:
        if not 0 < Decimal(value) <= Decimal("1000000000000"):
            raise ValueError("积分换算比例必须大于 0 且不超过 1000000000000")
        return value


class PointConversionView(BaseModel):
    id: UUID
    version: int
    currency: Currency
    points_per_currency: str
    created_at: datetime


class PointConversionSettings(BaseModel):
    conversion: PointConversionView | None


class PointPrice(BaseModel):
    status: Literal["ready", "no_price", "unconfigured", "currency_mismatch"]
    conversion: PointConversionView | None = None
    currency: Currency | None = None
    unit: Literal[1, 1000000] = 1000000
    metric: Literal["tokens", "characters", "search_units", "images", "seconds"] = "tokens"
    rates: dict[str, str | None] = Field(default_factory=dict)
    total: str | None = None


class ReasoningToggle(Input):
    type: Literal["toggle"] = "toggle"


class ReasoningEffort(Input):
    type: Literal["effort"] = "effort"
    values: list[Effort | None] = Field(min_length=1, max_length=9)

    @field_validator("values")
    @classmethod
    def unique(cls, value: list[Effort | None]) -> list[Effort | None]:
        if len(set(value)) != len(value):
            raise ValueError("思考强度不能重复")
        return value


class ReasoningBudget(Input):
    type: Literal["budget_tokens"] = "budget_tokens"
    min: int | None = Field(default=None, ge=-1, le=100000000)
    max: int | None = Field(default=None, ge=0, le=100000000)

    @model_validator(mode="after")
    def bounds(self) -> Self:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("思考预算下限不能超过上限")
        return self


ReasoningOption = Annotated[
    ReasoningToggle | ReasoningEffort | ReasoningBudget, Field(discriminator="type")
]


def effective_reasoning_format(
    reasoning_format: Literal["openai", "thinking", "thinking_budget", "enable_thinking"],
    options: list[ReasoningOption],
) -> Literal["openai", "thinking", "thinking_budget", "enable_thinking"]:
    """Return the executable dialect for a model's declared reasoning controls.

    Older bindings may have kept the default ``openai`` format even after a
    model was changed to expose only a boolean thinking toggle.  OpenAI's
    effort field cannot represent that contract, so treating this specific
    contradictory combination as the native ``enable_thinking`` format keeps
    the public catalog and the LiteLLM request builder in sync.  Models that
    declare effort values, budgets, or an explicit non-default format retain
    their configured behavior.
    """
    types = {option.type for option in options}
    if reasoning_format == "openai" and "toggle" in types and "effort" not in types:
        return "enable_thinking"
    return reasoning_format


class CatalogReference(Input):
    provider: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=300)
    channel_id: UUID | None = None


class TokenPrice(Input):
    currency: Currency
    unit: Literal[1, 1000, 1000000] = 1000000
    input: Rate
    output: Rate | None = None
    metric: Literal["tokens", "characters", "search_units", "images", "seconds"] = "tokens"
    cache_read: Rate | None = None
    cache_write_5m: Rate | None = None
    cache_write_1h: Rate | None = None
    note: str = Field(default="", max_length=500)

    @field_validator(*RATE_FIELDS, mode="before")
    @classmethod
    def decimal_string(cls, value: object) -> object:
        # Avoid accepting a JSON float that has already lost decimal precision.
        if value is not None and not (
            isinstance(value, Decimal)
            or isinstance(value, str)
            and re.fullmatch(r"\d{1,10}(?:\.\d{1,15})?", value)
        ):
            raise ValueError("单价须为非负十进制字符串")
        return value

    @model_validator(mode="after")
    def normalize_unit(self) -> Self:
        if self.metric in ("images", "seconds"):
            if self.unit != 1 or any(getattr(self, key) is not None for key in RATE_FIELDS[1:]):
                raise ValueError("图片按张、转写按秒计价，只填写单价")
        elif self.unit == 1:
            raise ValueError("此计量单位只支持每千或每百万单价")
        if self.unit == 1000:
            for key in RATE_FIELDS:
                value = getattr(self, key)
                if value is not None:
                    value *= 1000
                    if value > 1000000000:
                        raise ValueError("规范化单价不能超过 10 亿／百万计量单位")
                    setattr(self, key, value)
            self.unit = 1000000
        for key in RATE_FIELDS:
            value = getattr(self, key)
            if value is not None and value != value.quantize(Decimal("0.000000000001")):
                raise ValueError("每百万计量单位单价最多支持 12 位小数")
        return self

    @field_serializer(*RATE_FIELDS)
    def decimal_output(self, value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None


class ModelCapabilities(Input):
    streaming: Declaration = "unknown"
    tools: Declaration = "unknown"
    structured_output: Declaration = "unknown"
    vision: Declaration = "unknown"
    reasoning: Declaration = "unknown"


class SamplingRule(Input):
    default: float | None = Field(default=None, ge=0, le=2, allow_inf_nan=False)
    adjustable: bool = True
    min: float = Field(default=0, ge=0, le=2, allow_inf_nan=False)
    max: float = Field(default=2, ge=0, le=2, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.min > self.max or (
            self.default is not None and not self.min <= self.default <= self.max
        ):
            raise ValueError("参数默认值及范围不一致")
        return self


class ChatPolicy(Input):
    default_context_window: int | None = Field(default=None, ge=1, le=100000000)
    default_max_output: int | None = Field(default=None, ge=1, le=100000000)
    context_adjustable: bool = True
    output_adjustable: bool = True
    default_reasoning_effort: Effort | None = None
    reasoning_adjustable: bool = True
    temperature: SamplingRule | None = None
    top_p: SamplingRule | None = None


class ChatRouteLimits(Input):
    context_window: int | None = Field(default=None, ge=1, le=100000000)
    max_output: int | None = Field(default=None, ge=1, le=100000000)
    reasoning_efforts: list[Effort] | None = Field(default=None, max_length=8)
    # None inherits model/SDK constraints. [] explicitly forbids these optional parameters.
    parameters: list[Literal["temperature", "top_p", "reasoning_effort", "thinking"]] | None = None


class ChatOptions(Input):
    limits: ChatRouteLimits = Field(default_factory=ChatRouteLimits)
    reasoning_format: Literal["openai", "thinking", "thinking_budget", "enable_thinking"] = "openai"
    output_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_completion_tokens"


class ModelBinding(Input):
    binding_id: UUID | None = None
    channel_id: UUID
    upstream_id: ModelIdentifier
    price: TokenPrice | None = None
    enabled: bool = Field(
        default=True,
        description="新绑定省略时关闭；编辑省略时保留。读取旧存量缺字段时兼容为启用。",
        json_schema_extra={"default": False},
    )
    priority: int = Field(default=0, ge=0, le=1000)
    weight: int = Field(default=100, ge=1, le=10000)
    compatibility_key: str = Field(default="", max_length=200)
    chat_options: ChatOptions = Field(default_factory=ChatOptions)


class RetrievalOptions(Input):
    max_search_units: int | None = Field(default=None, ge=1, le=1000000)
    dimensions: int | None = Field(default=None, ge=1, le=65536)
    dimension_options: list[int] = Field(default_factory=list, max_length=32)
    embedding_space: str = Field(default="", max_length=200)
    max_batch_size: int = Field(default=32, ge=1, le=128)
    max_input_characters: int = Field(default=20000, ge=1, le=200000)

    @model_validator(mode="after")
    def dimensions_valid(self) -> Self:
        if any(d < 1 or d > 65536 for d in self.dimension_options):
            raise ValueError("向量维度须为 1 至 65536")
        if len(set(self.dimension_options)) != len(self.dimension_options):
            raise ValueError("可选维度不能重复")
        if self.dimension_options and self.dimensions not in self.dimension_options:
            raise ValueError("可选维度须包含默认维度")
        return self


class ModelAccess(Input):
    enabled: bool = False
    audience: Literal["administrators", "organization", "selected"] = "administrators"
    member_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    channel_id: UUID | None = None
    upstream_id: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def valid_access(self) -> Self:
        if self.audience == "selected" and not self.member_ids:
            raise ValueError("指定成员至少选择一人")
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("成员不能重复")
        return self


class RoutingPolicy(Input):
    mode: Literal["fixed", "auto"] = "fixed"
    fallback: bool = False
    max_attempts: int = Field(default=3, ge=1, le=10)
    connect_timeout_seconds: int = Field(default=10, ge=1, le=120)
    first_response_timeout_seconds: int = Field(default=180, ge=3, le=3600)
    stream_idle_timeout_seconds: int = Field(default=180, ge=3, le=3600)
    total_timeout_seconds: int = Field(default=1800, ge=3, le=86400)
    retry_uncertain: bool = False
    failure_threshold: int = Field(default=3, ge=1, le=10)
    cooldown_seconds: int = Field(default=30, ge=5, le=3600)
    model_revision: str = Field(default="", max_length=200)


class GatewayExecution(Input):
    """Internal publication pointer; routing and actual prices remain in New API."""

    origin_hash: str = Field(min_length=64, max_length=64)
    capability_mode: Literal["auto", "manual"] = "manual"
    capability_source: dict[str, str] = Field(default_factory=dict)
    reserve_usd: str = Field(
        default="0.01",
        pattern=r"^(0|[1-9][0-9]{0,5})(\.[0-9]{1,8})?$",
        deprecated=True,
        description="Legacy compatibility field; reservations are calculated by New API.",
    )

    @field_validator("reserve_usd")
    @classmethod
    def positive_reserve(cls, value: str) -> str:
        if Decimal(value) <= 0:
            raise ValueError("单次预留额度须大于零")
        return value


class OperationParameters(Input):
    gateway: GatewayExecution | None = None
    chat_policy: ChatPolicy = Field(default_factory=ChatPolicy)
    kind: OperationKind = "chat"
    image: ImageOptions = Field(default_factory=ImageOptions)
    speech: SpeechOptions = Field(default_factory=SpeechOptions)
    transcription: TranscriptionOptions = Field(default_factory=TranscriptionOptions)
    retrieval: RetrievalOptions = Field(default_factory=RetrievalOptions)
    routing: RoutingPolicy = Field(default_factory=RoutingPolicy)
    context_window: int | None = Field(default=None, ge=1, le=100000000)
    max_output: int | None = Field(default=None, ge=1, le=100000000)
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    reasoning_options: list[ReasoningOption] = Field(default_factory=list, max_length=3)
    bindings: list[ModelBinding] = Field(default_factory=list, max_length=50)
    budget_price: TokenPrice | None = None

    def validate_operation(self, enabled: bool, channel_id: UUID | None, upstream_id: str) -> None:
        if self.kind == "transcription":
            if self.routing.mode != "fixed":
                raise ValueError("语音转文字自动匹配只允许单次调用")
            if enabled and self.budget_price is None and self.gateway is None:
                raise ValueError("开放转写前请配置每秒积分计价")
        if self.kind == "speech":
            if self.routing.mode != "fixed":
                raise ValueError("语音合成自动匹配只允许单次调用")
            if enabled and (
                not self.speech.voice or (self.budget_price is None and self.gateway is None)
            ):
                raise ValueError("开放语音合成前请配置音色和字符计价")
        if self.kind == "image_generation":
            if self.routing.mode != "fixed":
                raise ValueError("图片生成自动匹配只允许单次调用")
            if enabled and self.budget_price is None and self.gateway is None:
                raise ValueError("开放图片生成前请配置每张积分计价")
        if enabled and self.routing.mode == "fixed" and (channel_id is None or not upstream_id):
            raise ValueError("启用前请选择调用渠道")
        if self.kind == "chat" and enabled and (not self.context_window or not self.max_output):
            raise ValueError("开放对话前请设置上下文和输出上限")
        if (
            self.kind == "embedding"
            and enabled
            and (self.retrieval.dimensions is None or not self.retrieval.embedding_space)
        ):
            raise ValueError("启用向量模型前填写默认维度与向量空间标识")
        for price in [self.budget_price, *[b.price for b in self.bindings]]:
            if price is None:
                continue
            if (self.kind == "image_generation") != (price.metric == "images"):
                raise ValueError("图片生成使用按张价格，其他操作不能使用图片价格")
            if (self.kind == "transcription") != (price.metric == "seconds"):
                raise ValueError("语音转文字使用每秒价格，其他操作不能使用时长价格")
            if self.kind == "speech" and price.metric != "characters":
                raise ValueError("语音合成使用输入字符计价")
            if self.kind == "chat" and (price.metric != "tokens" or price.output is None):
                raise ValueError("对话模型需要输入与输出 Token 价格")
            if self.kind != "chat" and any(getattr(price, k) is not None for k in RATE_FIELDS[1:]):
                raise ValueError("此操作只配置输入单价")
            if self.kind == "embedding" and price.metric == "search_units":
                raise ValueError("向量模型不使用搜索计费单位")
        types = [option.type for option in self.reasoning_options]
        if len(set(types)) != len(types):
            raise ValueError("思考控制类型不能重复")
        if types and self.capabilities.reasoning != "supported":
            raise ValueError("只有支持思考的模型可配置思考参数")
        if self.context_window and self.max_output and self.max_output > self.context_window:
            raise ValueError("最大输出不能大于上下文上限")
        if self.kind == "chat":
            policy = self.chat_policy
            for chosen, maximum in (
                (policy.default_context_window, self.context_window),
                (policy.default_max_output, self.max_output),
            ):
                if chosen is not None and (maximum is None or chosen > maximum):
                    raise ValueError("默认值不能超过模型上限")
            if (
                policy.default_context_window
                and (policy.default_max_output or self.max_output or 0)
                >= policy.default_context_window
            ):
                raise ValueError("默认上下文必须为输入和输出保留空间")
            effort = next(
                (o for o in self.reasoning_options if isinstance(o, ReasoningEffort)), None
            )
            if policy.default_reasoning_effort is not None and (
                effort is None or policy.default_reasoning_effort not in effort.values
            ):
                raise ValueError("默认思考强度不在允许选项中")
            if policy.top_p and policy.top_p.max > 1:
                raise ValueError("top_p 上限不能超过 1")
        keys = [(b.channel_id, b.upstream_id) for b in self.bindings]
        if len(keys) != len(set(keys)):
            raise ValueError("不能重复关联同一渠道和上游模型")


class ModelOperation(OperationParameters):
    enabled: bool = False
    channel_id: UUID | None = None
    upstream_id: str = Field(default="", max_length=200)


class CatalogInput(OperationParameters):
    slug: ModelIdentifier
    name: str = Field(min_length=1, max_length=100)
    vendor: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="", max_length=350000)
    icon_key: str = Field(default="", pattern=r"^[a-z0-9-]{0,100}$")
    reference: CatalogReference | None = None
    display_order: int = Field(default=0, ge=0, le=1000000, strict=True)
    quote_snapshots: list[QuoteSnapshot] = Field(default_factory=list, max_length=10)
    access: ModelAccess = Field(default_factory=ModelAccess)
    # None accepts legacy clients. An explicit list is authoritative, including an empty draft.
    operations: list[ModelOperation] | None = Field(default=None, max_length=6)

    def operation_configs(self) -> list[ModelOperation]:
        if self.operations is not None:
            return self.operations
        return [
            ModelOperation.model_validate(
                {
                    **self.model_dump(include=set(OperationParameters.model_fields)),
                    "enabled": True,
                    "channel_id": self.access.channel_id,
                    "upstream_id": self.access.upstream_id,
                }
            )
        ]

    def for_operation(self, kind: OperationKind) -> "CatalogInput | None":
        operation = next((o for o in self.operation_configs() if o.kind == kind), None)
        if operation is None:
            return None
        data = self.model_dump(include=set(CatalogInput.model_fields))
        data.update(operation.model_dump(include=set(OperationParameters.model_fields)))
        data["operations"] = None
        data["access"] = {
            **self.access.model_dump(),
            "enabled": self.access.enabled and operation.enabled,
            "channel_id": operation.channel_id,
            "upstream_id": operation.upstream_id,
        }
        return CatalogInput.model_validate(data)

    def execution_configs(self) -> list["CatalogInput"]:
        return [
            config
            for o in self.operation_configs()
            if (config := self.for_operation(o.kind)) is not None
        ]

    @model_validator(mode="after")
    def compatible_limits(self) -> Self:
        if self.operations is None:
            self.validate_operation(
                self.access.enabled, self.access.channel_id, self.access.upstream_id
            )
            return self
        kinds = [o.kind for o in self.operations]
        if len(kinds) != len(set(kinds)):
            raise ValueError("同一操作只能配置一次")
        if self.access.enabled and not any(o.enabled for o in self.operations):
            raise ValueError("启用模型前请至少开放一项操作")
        for operation in self.operations:
            operation.validate_operation(
                self.access.enabled and operation.enabled,
                operation.channel_id,
                operation.upstream_id,
            )
        # Keep legacy display fields as a derived projection, never another source of truth.
        first = self.operations[0] if self.operations else ModelOperation()
        for key in OperationParameters.model_fields:
            setattr(self, key, getattr(first, key))
        self.access = self.access.model_copy(
            update={
                "channel_id": first.channel_id,
                "upstream_id": first.upstream_id,
            }
        )
        return self


class CatalogUpdate(CatalogInput):
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def compatible_limits(self) -> Self:
        # Older clients omit extension fields. Validate cross-field rules only after
        # configure() merges those fields and reparses the full CatalogInput.
        return self


class BindingState(BaseModel):
    operation: OperationKind = "chat"
    binding_id: UUID
    channel_id: UUID
    upstream_id: str
    channel_name: str
    state: Literal["registered", "archived", "missing"]


class EndpointSummary(BaseModel):
    configured_count: int
    ready_count: int
    reasons: list[str] = Field(default_factory=list)
    member_authorization: Literal["not_evaluated"] = "not_evaluated"


class CatalogView(CatalogInput):
    id: UUID
    version: int
    archived: bool
    binding_states: list[BindingState]
    created_at: datetime
    updated_at: datetime
    point_price: PointPrice | None = None
    operation_point_prices: dict[str, PointPrice] = Field(default_factory=dict)
    endpoint_summary: EndpointSummary | None = None


class CatalogPage(BaseModel):
    items: list[CatalogView]
    total: int


class TokenUsage(Input):
    input: int = Field(default=0, ge=0, le=1000000000000)
    output: int = Field(default=0, ge=0, le=1000000000000)
    cache_read: int = Field(default=0, ge=0, le=1000000000000)
    cache_write_5m: int = Field(default=0, ge=0, le=1000000000000)
    cache_write_1h: int = Field(default=0, ge=0, le=1000000000000)


class PriceEstimateInput(Input):
    price: TokenPrice
    usage: TokenUsage
    include_points: bool = False


class EstimateItem(BaseModel):
    item: str
    tokens: int
    rate: str | None
    amount: str


class PriceEstimateView(BaseModel):
    currency: Currency
    total: str
    items: list[EstimateItem]
    points: PointPrice | None = None
