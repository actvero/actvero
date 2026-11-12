from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

WorkbenchAudience = Literal["administrators", "selected", "organization"]
WorkbenchCategory = Literal[
    "office",
    "engineering",
    "design",
    "content",
    "data",
    "education",
    "lifestyle",
    "general",
    "uncategorized",
]
WorkbenchStatus = Literal["draft", "published", "withdrawn"]
ConfigKey = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")]
ConfigValue = Annotated[str, Field(max_length=2048)]


class WorkbenchConfigField(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, strict=True)
    key: ConfigKey
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    kind: Literal["text", "url"] = "text"
    required: bool = False
    default: ConfigValue | None = None


class WorkbenchRevision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class WorkbenchMetadata(WorkbenchRevision):
    model_config = ConfigDict(str_strip_whitespace=True)
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=1024)
    category: WorkbenchCategory


class WorkbenchScope(WorkbenchRevision):
    audience: WorkbenchAudience
    member_ids: list[UUID] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def validate_members(self) -> "WorkbenchScope":
        if (self.audience == "selected") != bool(self.member_ids):
            raise ValueError("仅指定成员范围需要选择成员")
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("成员不能重复")
        return self


class WorkbenchPublish(WorkbenchRevision):
    model_config = ConfigDict(str_strip_whitespace=True)
    release_notes: str = Field(default="", max_length=4000)


class WorkbenchConfigUpdate(WorkbenchRevision):
    version_id: UUID
    values: dict[ConfigKey, ConfigValue] = Field(max_length=32)


WorkbenchDigest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class DesktopWorkbenchRelease(BaseModel):
    workbench_id: UUID
    version_id: UUID
    package_name: str
    display_name: str
    description: str
    icon_data_url: str | None = None
    preview_data_urls: list[str] = Field(default_factory=list, max_length=3)
    category: WorkbenchCategory
    version: str
    dsh_requirement: str
    size: int
    sha256: WorkbenchDigest


class DesktopWorkbenchCatalog(BaseModel):
    items: list[DesktopWorkbenchRelease]


class DesktopWorkbenchPin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workbench_id: UUID
    version_id: UUID
    sha256: WorkbenchDigest


class DesktopWorkbenchCheck(BaseModel):
    status: Literal["current", "update_available", "unavailable"]
    adopted_usable: bool


class WorkbenchConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_name: str = Field(min_length=1, max_length=214)
    version: str = Field(min_length=1, max_length=80)


class WorkbenchRuntimeConfig(BaseModel):
    values: dict[ConfigKey, ConfigValue]


class WorkbenchVersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: str
    status: Literal["draft", "published", "superseded", "withdrawn"]
    dsh_requirement: str
    size: int
    sha256: str
    release_notes: str
    uploader_name: str
    created_at: datetime
    published_at: datetime | None
    config_fields: list[WorkbenchConfigField]


class WorkbenchSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    package_name: str
    display_name: str
    description: str
    icon_data_url: str | None = None
    category: WorkbenchCategory
    audience: WorkbenchAudience
    status: WorkbenchStatus
    current_version: str | None
    has_draft: bool
    updated_at: datetime


class WorkbenchView(WorkbenchSummary):
    revision: int
    member_ids: list[UUID]
    versions: list[WorkbenchVersionView]
    config_values: dict[ConfigKey, ConfigValue]


class WorkbenchPage(BaseModel):
    items: list[WorkbenchSummary]
    total: int
