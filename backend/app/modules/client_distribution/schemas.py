import base64
import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.object_storage.schemas import StorageSave, StorageView  # noqa: F401
from app.modules.object_storage.validation import Input, https_url
from app.modules.platform.download_schemas import ClientAsset

Target = Literal["win-x64", "win-arm64", "mac-arm64", "mac-x64"]
Channel = Literal["latest", "nightly"]
Role = Literal["installer", "payload", "blockmap"]
TARGETS = ("win-x64", "win-arm64", "mac-arm64", "mac-x64")
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?$"
)


class DistributionSave(Input):
    expected_revision: int = Field(ge=0)
    version: str = Field(max_length=50)
    channel: Channel = "latest"
    notes: str = Field(default="", max_length=12000)
    source_commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    minimum_os: dict[Target, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def version_channel(self) -> "DistributionSave":
        if not SEMVER.fullmatch(self.version):
            raise ValueError("更新版本须为 SemVer，不使用构建元数据")
        if self.channel == "latest" and "-" in self.version:
            raise ValueError("正式通道不能发布预发布版本号")
        if any(not v.strip() or len(v) > 100 for v in self.minimum_os.values()):
            raise ValueError("请填写有效的最低系统版本")
        return self


class ArtifactCreate(Input):
    expected_revision: int = Field(ge=1)
    target: Target
    role: Role
    filename: str = Field(min_length=1, max_length=180, pattern=r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
    size_bytes: int | None = Field(default=None, gt=0, le=20_000_000_000)
    sha512: str | None = None
    url: str | None = Field(default=None, max_length=2048)
    storage_id: UUID | None = None
    mirror: bool = False

    @field_validator("url")
    @classmethod
    def address(cls, value: str | None) -> str | None:
        return https_url(value) if value else value

    @field_validator("sha512")
    @classmethod
    def checksum(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                if len(base64.b64decode(value, validate=True)) != 64:
                    raise ValueError()
            except ValueError:
                raise ValueError("SHA-512 必须是完整摘要的 base64 编码") from None
        return value

    @model_validator(mode="after")
    def source_rules(self) -> "ArtifactCreate":
        if not self.url and not self.size_bytes:
            raise ValueError("上传文件需要文件大小")
        if self.mirror and not self.url:
            raise ValueError("转存需要来源地址")
        if self.url and not self.mirror and urlsplit(self.url).query:
            raise ValueError("长期引用不能使用带查询参数的地址，请选择转存")
        extension = ".exe" if self.target.startswith("win-") else ".zip"
        expected = (
            extension + ".blockmap"
            if self.role == "blockmap"
            else (
                ".dmg"
                if self.role == "installer" and not self.target.startswith("win-")
                else extension
            )
        )
        if self.target.startswith("win-") and self.role == "installer":
            raise ValueError("Windows EXE 请使用更新包角色，同时用于下载安装")
        if not self.filename.endswith(expected):
            raise ValueError("文件扩展名与目标用途不一致")
        return self


class ArtifactView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    release_id: UUID
    target: Target
    role: Role
    filename: str
    source: str
    url: str | None
    storage_id: UUID | None
    size_bytes: int | None
    sha512: str | None
    sha256: str | None
    status: str
    error: str | None
    published_at: datetime | None


class DistributionView(BaseModel):
    id: UUID
    version: str
    channel: Channel
    notes: str
    minimum_os: dict[str, str]
    status: str
    revision: int
    source_commit: str | None = None
    legacy: bool = False
    legacy_assets: list[ClientAsset] = Field(default_factory=list)
    artifacts: list[ArtifactView]


class Revision(Input):
    expected_revision: int = Field(ge=1)


class PartsSign(Input):
    parts: list[int] = Field(min_length=1, max_length=16)

    @field_validator("parts")
    @classmethod
    def numbers(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value) or any(p < 1 or p > 10000 for p in value):
            raise ValueError("分片编号无效")
        return value


class PartAck(Input):
    number: int = Field(ge=1, le=10000)
    etag: str = Field(min_length=1, max_length=200, pattern=r'^[A-Za-z0-9"._-]+$')


class UploadView(BaseModel):
    id: UUID
    artifact_id: UUID
    status: str
    part_size: int
    part_count: int
    size_bytes: int
    expected_sha512: str | None
    parts: dict[str, str]
    expires_at: datetime


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    artifact_id: UUID
    status: str
    processed_bytes: int
    error: str | None


class PlanCreate(Revision):
    targets: list[Target] = Field(min_length=1, max_length=3)


class Publish(Input):
    plan_id: UUID


class HeadView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    channel: Channel
    target: Target
    release_id: UUID | None
    revision: int


class PlanView(BaseModel):
    id: UUID
    release_id: UUID
    release_revision: int
    targets: dict[str, int]
    expires_at: datetime


__all__ = ["StorageSave", "StorageView", "https_url"]
