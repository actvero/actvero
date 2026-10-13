from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.auth.schemas import UserView
from app.modules.desktop.schemas import (
    ExchangeLogin,
    LoginAttempt,
    LoginProof,
    LogoutSession,
    RefreshAcknowledgement,
    RefreshSession,
)
from app.modules.llm.schemas import ChannelDetail, ChannelPage


class StartLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal[1]
    redirect_uri: str = Field(max_length=200)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    device_name: str = Field(min_length=1, max_length=100)
    reauthenticate: bool = False

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
    scope: Literal["management:read"] = "management:read"
    session_id: UUID
    expires_in: int
    server_time: datetime
    session_expires_at: datetime
    reauthenticate_at: datetime
    refresh_request_id: UUID | None = None
    recovery_until: datetime | None = None


class Metadata(BaseModel):
    contract_version: Literal[1] = 1
    instance_id: UUID
    platform_name: str
    client_id: str
    issuer: str
    scope: Literal["management:read"] = "management:read"
    callback_template: str = "http://127.0.0.1:{port}/actvero/cli/callback"
    access_seconds: int
    recovery_days: int
    reauthentication_days: int
    capabilities: list[str] = Field(
        default_factory=lambda: [
            "auth.login",
            "auth.refresh",
            "auth.logout",
            "org.list",
            "org.show",
            "org.permissions",
            "channels.list",
            "channels.show",
        ]
    )


class Me(BaseModel):
    user: UserView
    session_id: UUID
    scope: Literal["management:read"] = "management:read"
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


class ChannelList(BaseModel):
    organization: Organization
    result: ChannelPage


class ChannelResult(BaseModel):
    organization: Organization
    result: ChannelDetail


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
