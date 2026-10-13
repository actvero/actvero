from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.mcp.schemas import InputModel


class ResourceTokenInput(InputModel):
    resource: str = Field(
        pattern=r"^((mcp|llm):(catalog|[0-9a-fA-F-]{36})|(skills|experts):catalog)$",
        description=(
            "experts:catalog 用于专家目录与依赖解析；skills:catalog 用于技能目录与下载；"
            "mcp:catalog 用于连接器目录和本人连接；"
            "mcp:<服务UUID> 用于该服务；llm:catalog 获取模型目录，llm:<模型UUID> 调用模型。"
        ),
        examples=["skills:catalog", "mcp:catalog", "llm:catalog"],
    )


class ResourceTokenView(BaseModel):
    access_token: str = Field(
        description="短期资源令牌，仅主进程持有；不能调用 Web 管理或桌面账号接口。"
    )
    token_type: Literal["Bearer"] = "Bearer"
    resource: str = Field(description="令牌绑定的资源，与申请值一致。")
    scope: str = Field(
        description="Experts 为 experts:read；Skills 为 skills:read skills:download；"
        "MCP 目录为 mcp:catalog mcp:connection，服务为 mcp:invoke；"
        "LLM 目录为 llm:catalog，单模型为 llm:invoke。"
    )
    expires_in: int = Field(description="剩余有效期，秒。最长 600 秒；不超过设备绝对期限。")
    endpoint: str = Field(description="该资源唯一适用的完整平台地址，不是上游地址。")


class ConnectionState(BaseModel):
    retry_after: int | None = Field(
        default=None, description="授权服务临时失败后的剩余等待秒数；不自动重试业务调用。"
    )
    status: Literal["not_connected", "unverified", "connected", "reauthorization_required", "error"]
    action: Literal["none", "configure", "authorize", "contact_admin", "retry"]
    error_code: str | None = Field(default=None, description="稳定原因码；不包含上游异常正文。")
    checked_at: datetime | None = Field(
        default=None, description="最近成功发现时间；并非实时健康保证。"
    )


class PersonalField(BaseModel):
    key: str = Field(description="提交 values 时使用的字段键。")
    label: str = Field(description="凭据输入框标签。所有字段必填，按密码控件处理。")


class CapabilityRevision(BaseModel):
    kind: Literal["tools", "prompts", "resources", "templates"]
    key: str
    contract_revision: str
    behavior_revision: str
    enabled: bool


class ConnectorRevisions(BaseModel):
    display: str
    connection: str
    authorization: str
    capabilities: str
    behavior: str


class Connector(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: str
    icon: str
    examples: list[str]
    auth_mode: Literal["none", "organization", "personal", "oauth"]
    credential_fields: list[PersonalField] = Field(
        description="仅 personal 返回表单字段，不含秘密或头部配置。"
    )
    connection: ConnectionState
    counts: dict[str, int] = Field(description="当前连接已发现且策略允许的能力数；未连接时可为 0。")
    revisions: ConnectorRevisions = Field(
        description="相互独立的展示、目标、授权、能力及行为指纹。"
    )
    capability_revisions: list[CapabilityRevision] = Field(
        description="本连接已发现且获准的 kind+key；修订仅为最近目录证据，不是实时可用保证。"
    )
    endpoint: str = Field(description="平台 Streamable HTTP MCP 地址，需申请此服务资源令牌。")


class ConnectorPage(BaseModel):
    items: list[Connector]
    total: int
    page: int
    page_size: int = 20


class PersonalCredentials(InputModel):
    values: dict[str, SecretStr] = Field(
        description="按 credential_fields 填写全部字段；仅写，不回显。"
    )


class OAuthAttemptView(BaseModel):
    id: UUID
    status: Literal[
        "pending",
        "exchanging",
        "awaiting_confirmation",
        "completed",
        "cancelled",
        "expired",
        "failed",
    ]
    expires_at: datetime
    error_code: str | None = None
    authorization_url: str | None = Field(
        default=None, description="仅发起时返回；主进程在系统浏览器打开，不记录日志。"
    )


class RpcRequest(BaseModel):
    model_config = ConfigDict(strict=True)
    jsonrpc: Literal["2.0"]
    id: str | int | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
