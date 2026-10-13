"""Bounded OpenAI-compatible chat contract; unknown parameters never disappear silently."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from app.modules.llm.catalog_schemas import Effort
from app.modules.llm.inference_schemas import InferenceInput


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SDKFields(BaseModel):
    """Preserve replay metadata returned by LiteLLM; top-level controls stay strict."""

    model_config = ConfigDict(extra="allow", strict=True)


class FunctionCall(SDKFields):
    name: str = Field(max_length=100000)
    arguments: str = Field(max_length=500000)


class ToolCall(SDKFields):
    provider_specific_fields: dict[str, Any] | None = None
    id: str = Field(max_length=131072)
    type: str = "function"
    function: FunctionCall


class ImageURL(Strict):
    url: str = Field(min_length=1, max_length=1500000)
    detail: Literal["auto", "low", "high"] = "auto"


class ContentPart(Strict):
    type: Literal["text", "image_url"]
    text: str | None = Field(default=None, max_length=1000000)
    image_url: ImageURL | None = None

    @model_validator(mode="after")
    def valid(self) -> Self:
        if (self.type == "text") != (self.text is not None) or (self.type == "image_url") != (
            self.image_url is not None
        ):
            raise ValueError("内容类型和字段不一致")
        if self.image_url and not self.image_url.url.startswith(("https://", "data:image/")):
            raise ValueError("图片须为 HTTPS 地址或 image data URL")
        return self


class ChatMessage(SDKFields):
    provider_specific_fields: dict[str, Any] | None = None
    thinking_blocks: list[dict[str, Any]] | None = Field(default=None, max_length=128)
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | list[ContentPart] | None = None
    name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$")
    tool_call_id: str | None = Field(default=None, min_length=1, max_length=131072)
    tool_calls: list[ToolCall] | None = Field(default=None, max_length=128)
    reasoning_content: str | None = Field(default=None, max_length=1000000)


class FunctionDefinition(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: str | None = Field(default=None, max_length=10000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    strict: bool | None = None


class Tool(Strict):
    type: Literal["function"] = "function"
    function: FunctionDefinition


class NamedFunction(Strict):
    name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")


class NamedTool(Strict):
    type: Literal["function"] = "function"
    function: NamedFunction


class ResponseFormat(Strict):
    type: Literal["text", "json_object", "json_schema"]
    json_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def valid(self) -> Self:
        if (self.type == "json_schema") != (self.json_schema is not None):
            raise ValueError("json_schema 格式需要 schema")
        if self.json_schema:
            if not isinstance(self.json_schema.get("name"), str) or not isinstance(
                self.json_schema.get("schema"), dict
            ):
                raise ValueError("需要 json_schema.name 和 json_schema.schema")
        return self


class Thinking(Strict):
    type: Literal["enabled", "disabled"]
    budget_tokens: int | None = Field(default=None, ge=1, le=100000000)


class StreamOptions(Strict):
    include_usage: bool = True


class ActveroChatOptions(Strict):
    context_window: int | None = Field(default=None, ge=1, le=100000000)
    configuration_version: int | None = Field(default=None, ge=1)
    purpose: Literal["conversation", "compaction", "session-title"] = "conversation"


class ChatInput(InferenceInput):
    actvero: ActveroChatOptions | None = None
    _input_reservation: int | None = PrivateAttr(default=None)
    _context_window: int | None = PrivateAttr(default=None)
    messages: list[ChatMessage] = Field(min_length=1, max_length=1000)
    stream: bool = False
    stream_options: StreamOptions | None = None
    n: Literal[1] = 1
    max_tokens: int | None = Field(default=None, ge=1, le=100000000)
    max_completion_tokens: int | None = Field(default=None, ge=1, le=100000000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    seed: int | None = None
    stop: str | list[str] | None = None
    tools: list[Tool] | None = Field(default=None, max_length=128)
    tool_choice: Literal["auto", "none", "required"] | NamedTool | None = None
    parallel_tool_calls: bool | None = None
    response_format: ResponseFormat | None = None
    reasoning_effort: Effort | None = None
    thinking: Thinking | None = None

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("仅填写一种输出上限")
        if self.stream_options and not self.stream:
            raise ValueError("stream_options 仅用于流式请求")
        if self.tool_choice not in (None, "none") and not self.tools:
            raise ValueError("tool_choice 需要 tools")
        if self.tools and len({t.function.name for t in self.tools}) != len(self.tools):
            raise ValueError("工具名不能重复")
        if isinstance(self.tool_choice, NamedTool) and self.tool_choice.function.name not in {
            t.function.name for t in self.tools or []
        }:
            raise ValueError("指定的工具不存在")
        if isinstance(self.stop, list) and (
            len(self.stop) > 4 or any(len(s) > 1000 for s in self.stop)
        ):
            raise ValueError("stop 最多 4 项，每项 1000 字符")
        # Tool IDs/order and provider replay metadata belong to SDK/provider
        # conversation validation, not a second platform state machine.
        return self
