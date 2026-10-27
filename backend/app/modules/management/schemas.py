from datetime import datetime
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.modules.auth.schemas import UserView
from app.modules.desktop.schemas import (
    ExchangeLogin,
    LoginAttempt,
    LoginProof,
    LogoutSession,
    RefreshAcknowledgement,
    RefreshSession,
)
from app.modules.desktop_mcp.schemas import OAuthAttemptView
from app.modules.llm.schemas import ChannelDetail, ChannelPage

ManagementScope = Literal["management:read", "management:read management:write", "platform:read"]
PlatformPermission = Literal["releases.write", "releases.publish", "storage.manage"]


class StartLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal[1]
    authorization_version: Literal[1, 2, 3] = 1
    target: Literal["organization", "platform"] = "organization"
    redirect_uri: str = Field(max_length=200)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    device_name: str = Field(min_length=1, max_length=100)
    reauthenticate: bool = False
    scope: ManagementScope = "management:read"

    @field_validator("redirect_uri")
    @classmethod
    def loopback(cls, value: str) -> str:
        p = urlsplit(value)
        if (
            p.scheme != "http"
            or p.hostname != "127.0.0.1"
            or not p.port
            or not 1024 <= p.port <= 65535
            or value != f"http://127.0.0.1:{p.port}/actvero/cli/callback"
        ):
            raise ValueError("仅支持 CLI 专用本机回调")
        return value

    @field_validator("device_name")
    @classmethod
    def display_text(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("设备名称无效")
        return value


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    scope: ManagementScope = "management:read"
    session_id: UUID
    expires_in: int
    server_time: datetime
    session_expires_at: datetime
    reauthenticate_at: datetime
    refresh_request_id: UUID | None = None
    recovery_until: datetime | None = None


class Metadata(BaseModel):
    contract_version: Literal[1] = 1
    authorization_contract_version: Literal[2] = 2
    supported_authorization_versions: list[int] = Field(default_factory=lambda: [1, 2, 3])
    client_distribution_contract_version: Literal[2] = 2
    instance_id: UUID
    platform_name: str
    client_id: str
    issuer: str
    scope: Literal["management:read"] = "management:read"
    supported_scopes: list[str] = Field(
        default_factory=lambda: ["management:read", "management:write", "platform:read"]
    )
    resource_contract_version: Literal[1] = 1
    callback_template: str = "http://127.0.0.1:{port}/actvero/cli/callback"
    access_seconds: int
    recovery_days: int
    reauthentication_days: int
    capabilities: list[str] = Field(
        default_factory=lambda: [
            "object_storage.read",
            "object_storage.write",
            "client_distribution.import_manifest",
            "client_distribution.win_arm64",
            "client_distribution.download_only",
            "client_distribution.read",
            "client_distribution.write",
            "auth.login",
            "auth.refresh",
            "auth.logout",
            "org.list",
            "org.show",
            "org.permissions",
            "channels.list",
            "channels.show",
            "skills.read",
            "skills.write",
            "mcp.read",
            "mcp.write",
            "experts.read",
            "experts.write",
            "commands.show",
            "skills.categories",
            "skills.download",
            "experts.categories",
            "mcp.oauth",
            "mcp.run",
            "mcp.activities",
            "mcp.contents",
        ]
    )


class Me(BaseModel):
    user: UserView
    session_id: UUID
    scope: ManagementScope = "management:read"
    platform_permissions: list[PlatformPermission] = Field(default_factory=list)
    authorized_org_ids: list[UUID] | None = None
    session_expires_at: datetime
    reauthenticate_at: datetime


class Organization(BaseModel):
    org_id: UUID
    name: str
    membership_id: UUID
    role: Literal["administrator", "member"]
    authority: Literal["membership", "platform"]
    available: bool
    reason: str | None = None
    permissions: list[str]


class Organizations(BaseModel):
    items: list[Organization]
    total: int
    page: int
    page_size: int = 50


class CliConsentProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_id: UUID
    state: SecretStr = Field(min_length=43, max_length=100)


class CliConsentDecision(CliConsentProof):
    platform_permissions: list[PlatformPermission] = Field(default_factory=list, max_length=3)
    approve: bool
    org_ids: list[UUID] = Field(default_factory=list, max_length=100)
    scope: ManagementScope = "management:read"


class CliConsentView(BaseModel):
    target: Literal["organization", "platform"] = "organization"
    device_name: str
    expires_at: datetime
    user: UserView
    organizations: list[Organization]


class CliConsentResult(BaseModel):
    redirect_url: str


class ChannelList(BaseModel):
    organization: Organization
    result: ChannelPage


class ChannelResult(BaseModel):
    organization: Organization
    result: ChannelDetail


Result = TypeVar("Result")


class ResourceResult[Result](BaseModel):
    organization: Organization
    result: Result
    request_id: UUID | None = None


class CommandStatus(BaseModel):
    request_id: UUID
    operation: str
    status: Literal["pending", "succeeded", "unknown"]
    result: dict[str, Any] | None
    created_at: datetime
    finished_at: datetime | None


__all__ = [
    "ChannelList",
    "ChannelResult",
    "ExchangeLogin",
    "LoginAttempt",
    "LoginProof",
    "LogoutSession",
    "Me",
    "Metadata",
    "Organization",
    "Organizations",
    "RefreshAcknowledgement",
    "RefreshSession",
    "StartLogin",
    "Tokens",
]


class ManagementOAuthView(OAuthAttemptView):
    authorization_url: str | None = Field(
        default=None,
        description="仅发起会话可读取；pending 状态下可恢复。包含临时 state，不应共享或记录日志。",
    )
