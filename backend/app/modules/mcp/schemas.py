import base64
import binascii
import re
from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.outbound import endpoint
from app.modules.account.service import normalize_avatar

Kind = Literal["tools", "prompts", "resources", "templates"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CredentialField(InputModel):
    key: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,49}$")
    label: str = Field(min_length=1, max_length=100)
    header: str = Field(min_length=1, max_length=100)
    bearer: bool = False

    @field_validator("header")
    @classmethod
    def safe_header(cls, value: str) -> str:
        # Only credential headers; never routing, cookie or MCP/session headers.
        if value.lower() not in {"authorization", "x-api-key", "api-key"} and not re.fullmatch(
            r"[Xx]-[A-Za-z0-9-]+", value
        ):
            raise ValueError("使用 Authorization、API-Key 或 X- 前缀的凭据头")
        if value.lower().startswith(("x-forwarded", "x-real-", "x-csrf", "x-actvero", "x-http-")):
            raise ValueError("不能覆盖平台或代理请求头")
        return value


class OAuthConfig(InputModel):
    authorization_url: str
    token_url: str
    client_id: str = Field(min_length=1, max_length=200)
    scopes: str = Field(default="", max_length=1000)
    _endpoints = field_validator("authorization_url", "token_url")(endpoint)


def normalize_icon(value: str) -> str:
    if not value:
        return ""
    if not re.match(r"^data:image/(png|jpeg|webp);base64,", value):
        raise HTTPException(422, "图标须为上传的 PNG、JPG 或 WebP 图片")
    try:
        data = base64.b64decode(value.split(",", 1)[1], validate=True)
        if len(data) > 256 * 1024:
            raise ValueError()
        normalized = normalize_avatar(data)
    except (ValueError, binascii.Error, HTTPException):
        raise HTTPException(422, "图标无效，请上传不超过 256 KB 的静态图片") from None
    return "data:image/webp;base64," + base64.b64encode(normalized).decode()


class McpPresentation(InputModel):
    display_name: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="", max_length=350000)
    examples: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("examples")
    @classmethod
    def valid_examples(cls, values: list[str]) -> list[str]:
        if any(not v.strip() or len(v) > 500 for v in values):
            raise ValueError("使用示例须为 1–500 个字符，最多 8 条")
        return [v.strip() for v in values]


class McpPresentationUpdate(McpPresentation):
    version: int = Field(ge=1)


class ConnectionOptions(InputModel):
    connect_timeout: int = Field(default=30, ge=1, le=120)
    request_timeout: int = Field(default=120, ge=1, le=600)
    total_timeout: int = Field(default=300, ge=1, le=900)
    reset_on_progress: bool = False
    health_enabled: bool = False
    health_interval: int = Field(default=60, ge=30, le=3600)

    @model_validator(mode="after")
    def timeouts(self) -> Self:
        if self.total_timeout < max(self.connect_timeout, self.request_timeout):
            raise ValueError("最大总耗时不能小于连接超时或请求超时")
        return self


class McpServiceInput(McpPresentation):
    connection_options: ConnectionOptions = Field(default_factory=ConnectionOptions)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    transport: Literal["http", "sse", "builtin"] = "http"
    url: str = ""
    enabled: bool = False
    audience: Literal["organization", "selected"] = "organization"
    member_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    auth_mode: Literal["none", "organization", "personal", "oauth"] = "none"
    credential_fields: list[CredentialField] = Field(default_factory=list, max_length=10)
    oauth: OAuthConfig | None = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.transport == "builtin":
            if self.url or self.auth_mode != "none":
                raise ValueError("内置内容不需要远程地址和凭据")
        else:
            endpoint(self.url)
        if self.auth_mode in {"organization", "personal"} and not self.credential_fields:
            raise ValueError("请定义至少一个凭据字段")
        if self.auth_mode == "oauth" and self.oauth is None:
            raise ValueError("请填写 OAuth 配置")
        if self.auth_mode != "oauth" and self.oauth is not None:
            raise ValueError("当前认证方式不使用 OAuth")
        if self.auth_mode not in {"organization", "personal"} and self.credential_fields:
            raise ValueError("当前认证方式不使用凭据字段")
        if len({f.key for f in self.credential_fields}) != len(self.credential_fields) or len(
            {f.header.lower() for f in self.credential_fields}
        ) != len(self.credential_fields):
            raise ValueError("凭据字段和请求头不能重复")
        return self


class McpServiceWrite(McpServiceInput):
    # Write-only; never include credentials in a view/export/preview.
    credential_values: dict[str, str] | None = None

    @model_validator(mode="after")
    def valid_credentials(self) -> Self:
        if self.credential_values is not None:
            if self.auth_mode != "organization":
                raise ValueError("此处只可保存组织凭据")
            validate_values(self.credential_fields, self.credential_values)
        return self


def validate_values(fields: list[CredentialField], values: dict[str, str]) -> None:
    if set(values) != {f.key for f in fields} or any(
        not v or len(v) > 8192 or any(ord(c) < 32 or ord(c) > 126 for c in v)
        for v in values.values()
    ):
        raise ValueError("请完整填写凭据，且不能包含控制字符或非 ASCII 字符")


class McpServiceUpdate(McpServiceWrite):
    version: int = Field(ge=1)


class McpServiceView(McpServiceInput):
    health_checked_at: datetime | None = None
    health_error: str | None = None
    id: UUID
    version: int
    configured: bool
    checked_at: datetime | None
    error: str | None
    protocol: str
    counts: dict[str, int]


class McpServicePage(BaseModel):
    items: list[McpServiceView]


class McpCapability(BaseModel):
    kind: Kind
    key: str
    name: str
    description: str
    original_description: str
    enabled: bool
    definition: dict[str, Any]


class McpCapabilities(BaseModel):
    items: list[McpCapability]
    protocol: str
    negotiated: dict[str, Any]
    checked_at: datetime | None
    error: str | None


class McpPolicyInput(InputModel):
    kind: Kind
    key: str = Field(min_length=1, max_length=2000)
    enabled: bool
    description: str | None = Field(default=None, max_length=10000)


class McpCredentials(InputModel):
    values: dict[str, str]


class McpRun(InputModel):
    kind: Kind
    key: str = Field(min_length=1, max_length=2000)
    arguments: dict[str, Any] = Field(default_factory=dict)
    uri: str | None = Field(default=None, max_length=2000)


class McpResult(BaseModel):
    result: dict[str, Any]
    duration_ms: int


class McpImport(InputModel):
    services: list[McpServiceInput] = Field(min_length=1, max_length=50)


class McpImportRequest(InputModel):
    configuration: dict[str, Any]


class McpImportPreviewItem(BaseModel):
    name: str
    transport: str
    auth_mode: str
    credential_count: int = 0
    has_credentials: bool = False
    error: str | None = None


class McpImportPreview(BaseModel):
    items: list[McpImportPreviewItem]
    valid: bool


class McpContentInput(InputModel):
    service_id: UUID
    kind: Literal["prompts", "resources"]
    name: str = Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    description: str = Field(default="", max_length=2000)
    body: str = Field(min_length=1, max_length=100000)
    arguments: list[str] = Field(default_factory=list, max_length=30)
    mime_type: Literal["text/plain", "text/markdown", "application/json"] = "text/plain"
    enabled: bool = False

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if any(not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,49}", a) for a in self.arguments) or len(
            set(self.arguments)
        ) != len(self.arguments):
            raise ValueError("参数名须唯一且仅含英文字母、数字、下划线")
        if self.kind == "resources" and self.arguments:
            raise ValueError("内置静态资源不使用提示词参数")
        if set(re.findall(r"\{\{(\w+)\}\}", self.body)) - set(self.arguments):
            raise ValueError("请先声明内容中使用的参数")
        return self


class McpContentView(McpContentInput):
    id: UUID


class McpContents(BaseModel):
    items: list[McpContentView]


class McpActivityView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    service_id: UUID
    service_name: str
    actor_name: str
    category: str
    operation: str
    capability: str
    source: str
    device_session_id: UUID | None = None
    client_version: str = ""
    result: str
    duration_ms: int
    error_code: str
    message: str
    request_id: str
    created_at: datetime


class McpActivityPage(BaseModel):
    items: list[McpActivityView]
    total: int
    page: int
    page_size: int = 20
