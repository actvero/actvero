import re
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Platform = Literal["windows", "macos"]
Architecture = Literal["x64", "arm64", "universal"]
ReleaseStatus = Literal["draft", "published", "withdrawn"]


class ClientAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    platform: Platform
    architecture: Architecture
    url: str = Field(default="", max_length=2048)
    filename: str = Field(default="", max_length=180)
    minimum_os: str = Field(default="", max_length=100)
    size_bytes: int | None = Field(default=None, gt=0, le=20_000_000_000, strict=True)
    sha256: str = Field(default="", max_length=64)

    @field_validator("url")
    @classmethod
    def safe_url(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or any(c.isspace() or ord(c) < 32 or c in '<>"\\' for c in value)
        ):
            raise ValueError("下载链接须为 HTTPS，不含账号、密码、片段或空白")
        try:
            _ = parsed.port
            parsed.hostname.encode("idna")
        except (ValueError, UnicodeError) as exc:
            raise ValueError("下载链接格式不正确") from exc
        return value

    @field_validator("filename", "minimum_os")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if any(ord(c) < 32 for c in value):
            raise ValueError("不能包含控制字符")
        return value

    @field_validator("sha256")
    @classmethod
    def checksum(cls, value: str) -> str:
        if value and not re.fullmatch(r"[a-fA-F0-9]{64}", value):
            raise ValueError("SHA256 须为 64 位十六进制")
        return value.lower()

    @model_validator(mode="after")
    def target(self) -> "ClientAsset":
        if self.platform == "windows" and self.architecture == "universal":
            raise ValueError("Windows 请选 x64 或 ARM64")
        if "/" in self.filename or "\\" in self.filename:
            raise ValueError("文件名不能包含路径")
        return self


class ReleaseRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1, strict=True)


class ReleaseSave(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=0, strict=True)
    version: str = Field(min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._+-]*$")
    release_date: date
    notes: str = Field(default="", max_length=12000)
    assets: list[ClientAsset] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def unique_targets(self) -> "ReleaseSave":
        keys = [(asset.platform, asset.architecture) for asset in self.assets]
        if len(set(keys)) != len(keys):
            raise ValueError("同一系统和架构只能有一个安装包")
        return self


class ReleasePublish(ReleaseRevision):
    recommend: bool = Field(default=False, strict=True)


class ReleaseView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: str
    release_date: date
    notes: str
    assets: list[ClientAsset]
    status: ReleaseStatus
    revision: int
    created_at: datetime
    updated_at: datetime


class RecommendationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    platform: Platform
    architecture: Architecture
    release_id: UUID


class RecommendationSave(ReleaseRevision):
    platform: Platform
    architecture: Architecture


class ReleasePage(BaseModel):
    items: list[ReleaseView]
    total: int
    recommendations: list[RecommendationView]


class PublicRelease(BaseModel):
    id: UUID
    version: str
    release_date: date
    notes: str
    assets: list[ClientAsset]


class PublicDownloads(BaseModel):
    items: list[PublicRelease]
    recommendations: list[RecommendationView]


class ReleaseEventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    actor_name: str
    action: str
    revision: int
    created_at: datetime
