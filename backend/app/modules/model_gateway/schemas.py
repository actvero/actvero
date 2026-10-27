from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr, field_validator

from app.core.outbound import endpoint


class GatewayStatus(BaseModel):
    configured: bool
    backend: Literal["newapi", "direct"]
    connected: bool = False
    error: str | None = None
    console_url: str | None = None


class GatewayResult(BaseModel):
    data: JsonValue = None


class GatewayChannelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    type: int = Field(ge=1, le=63)
    base_url: str = Field(default="", max_length=2000)
    key: SecretStr | None = None
    models: list[str] = Field(default_factory=list, max_length=1000)
    model_mapping: dict[str, str] = Field(default_factory=dict, max_length=1000)
    groups: list[str] = Field(default_factory=lambda: ["default"], min_length=1, max_length=30)
    priority: int = Field(default=0, ge=-999, le=2_147_483_647)
    weight: int = Field(default=1, ge=0, le=2_147_483_647)
    tag: str = Field(default="", max_length=100)
    test_model: str = Field(default="", max_length=200)
    auto_ban: int = Field(default=1, ge=0, le=1)
    param_override: str = Field(default="", max_length=10000)
    status_code_mapping: str = Field(default="", max_length=10000)
    revision: str | None = Field(default=None, max_length=64)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        return endpoint(value) if value else value

    @field_validator("models", "groups")
    @classmethod
    def valid_names(cls, values: list[str]) -> list[str]:
        if any(not v.strip() or len(v) > 200 or "," in v or "\n" in v for v in values):
            raise ValueError("名称不能为空，不能包含逗号或换行")
        return list(dict.fromkeys(v.strip() for v in values))

    @field_validator("model_mapping")
    @classmethod
    def valid_mapping(cls, value: dict[str, str]) -> dict[str, str]:
        if any(
            not k.strip() or not v.strip() or len(k) > 200 or len(v) > 200 for k, v in value.items()
        ):
            raise ValueError("模型映射须包含有效的模型名称与上游模型 ID")
        return value

    @field_validator("param_override", "status_code_mapping")
    @classmethod
    def valid_json(cls, value: str) -> str:
        import json

        if value and not isinstance(json.loads(value), dict):
            raise ValueError("须为 JSON 对象")
        return value


class GatewayChannelStatus(BaseModel):
    status: Literal[1, 2]


class GatewayDirectoryView(BaseModel):
    models: list[str]
    fetched_at: datetime | None = None


class GatewayDiscoveryInput(BaseModel):
    type: int = Field(ge=1, le=63)
    base_url: str = Field(max_length=2000)
    key: SecretStr

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        return endpoint(value) if value else value


class GatewayModelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model_name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=10000)
    icon: str = Field(default="", max_length=128)
    tags: str = Field(default="", max_length=255)
    vendor_id: int = Field(default=0, ge=0)
    endpoints: str = Field(default="", max_length=10000)
    status: Literal[0, 1] = 1
    sync_official: Literal[0, 1] = 1
    name_rule: Literal[0, 1, 2, 3] = 0
    revision: str | None = Field(default=None, max_length=64)


class GatewayMappingInput(BaseModel):
    channel_id: int = Field(gt=0)
    model_name: str = Field(min_length=1, max_length=128, pattern=r"^[^,\n]+$")
    upstream_id: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=64, max_length=64)
    remove: bool = False


class GatewayPriceInput(BaseModel):
    model_name: str = Field(min_length=1, max_length=128)
    expected_version: str = Field(min_length=1, max_length=128)
    pricing: dict[str, JsonValue] = Field(max_length=20)
    reset: bool = False


class GatewayPricePreview(BaseModel):
    model_name: str = Field(min_length=1, max_length=128)
    pricing: dict[str, JsonValue] = Field(max_length=20)


class GatewayTestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(default="", max_length=200)
    endpoint_type: Literal[
        "auto",
        "openai",
        "openai-response",
        "openai-response-compact",
        "anthropic",
        "gemini",
        "jina-rerank",
        "image-generation",
        "embeddings",
    ] = "auto"
    stream: bool = False


class GatewayChannelPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str | None = Field(default=None, min_length=64, max_length=64)
    priority: int | None = Field(default=None, ge=-999, le=2_147_483_647)
    weight: int | None = Field(default=None, ge=0, le=2_147_483_647)
    models: list[str] | None = Field(default=None, max_length=1000)

    @field_validator("models")
    @classmethod
    def valid_models(cls, value: list[str] | None) -> list[str] | None:
        return GatewayChannelInput.valid_names(value) if value is not None else None


class GatewayDeleteInput(BaseModel):
    remove_from_channels: bool = False
    remove_pricing: bool = False


class GatewayVendorInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=10000)
    icon: str = Field(default="", max_length=128)
    status: Literal[0, 1] = 1


class GatewayReferenceSelection(BaseModel):
    model_name: str = Field(min_length=1, max_length=128)
    record_version: str = Field(max_length=128)
    create: bool
    fields: list[
        Literal["description", "icon", "tags", "vendor", "endpoints", "name_rule", "status"]
    ] = Field(max_length=7)


class GatewayReferenceImport(BaseModel):
    source_version: str = Field(min_length=1, max_length=128)
    selections: list[GatewayReferenceSelection] = Field(min_length=1, max_length=100)
