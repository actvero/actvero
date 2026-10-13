from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.experts.dependency_schemas import ExpertDraftSelection
from app.modules.skills.categories import CategoryId
from app.modules.skills.icons import library_image, uploaded_image

Audience = Literal["administrators", "selected", "organization"]


class SkillIconSelectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["auto", "library", "upload"] = "auto"
    key: str = Field(default="", max_length=100)
    image: str = Field(default="", max_length=350000, repr=False)


class SkillIconSelection(SkillIconSelectionView):
    @model_validator(mode="after")
    def validate_source(self) -> "SkillIconSelection":
        if self.source == "library":
            library_image(self.key)
            if self.image:
                raise ValueError("图标库不接受自定义图片")
        elif self.source == "upload":
            if self.key:
                raise ValueError("上传图标不接受图标库标识")
            self.image = uploaded_image(self.image)
        elif self.key or self.image:
            raise ValueError("自动图标不接受手动设置")
        return self


class SkillIcon(BaseModel):
    source: Literal["fallback", "package", "library", "upload"] = "fallback"
    image: str = Field(default="", description="规范化图片 data URL；空值时客户端显示名称首字母")
    sha256: str = Field(default="", description="图片字节 SHA-256，可用于桌面端缓存失效")


class SkillIconOption(BaseModel):
    key: str
    label: str
    category: str
    image: str


class SkillScope(BaseModel):
    audience: Audience
    member_ids: list[UUID] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def scope(self) -> "SkillScope":
        if self.audience == "selected" and not self.member_ids:
            raise ValueError("请选择至少一名成员")
        if self.audience != "selected" and self.member_ids:
            raise ValueError("此范围不应包含指定成员")
        if len(self.member_ids) != len(set(self.member_ids)):
            raise ValueError("成员不能重复")
        return self


class SkillMetadata(SkillScope):
    category: CategoryId | None = Field(
        default=None, description="技能级单选类别；新建省略为未分类，更新省略/null 保留原值。"
    )
    icon_selection: SkillIconSelection | None = Field(
        default=None, description="省略或 null 保留原设置；auto 恢复跟随生效版本包内图标"
    )

    @field_validator("display_name", "description", mode="before")
    @classmethod
    def trimmed(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1024)


class SkillUpdate(SkillMetadata):
    revision: int


class SkillFile(BaseModel):
    sha256: str = ""
    path: str
    size: int
    previewable: bool


class SkillPreview(BaseModel):
    package_icon: str = ""
    icon_warning: str = ""
    name: str
    description: str
    skill_md: str
    files: list[SkillFile]
    sha256: str
    size: int


class SkillVersionView(BaseModel):
    package_icon: str = ""
    icon_warning: str = ""
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: str
    status: Literal["draft", "published", "superseded", "withdrawn"]
    release_notes: str
    uploader_name: str
    sha256: str
    size: int
    files: list[SkillFile]
    created_at: datetime
    published_at: datetime | None


class SkillView(BaseModel):
    category: CategoryId = "uncategorized"
    category_name: str = "未分类"
    icon: SkillIcon = Field(default_factory=SkillIcon)
    icon_selection: SkillIconSelectionView | None = None
    display_name: str
    description: str
    audience: Audience
    member_ids: list[UUID]
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    revision: int
    default_version_id: UUID | None = Field(
        description="当前唯一生效的已发布版本；无生效版本时为空。保留原字段名，不再单独设置默认版本。"
    )
    versions: list[SkillVersionView]
    downloads: int
    created_at: datetime


class SkillPage(BaseModel):
    items: list[SkillView]
    total: int
    page: int


class SkillAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int
    action: Literal["publish", "withdraw"]
    request_id: UUID | None = None
    draft_updates: list[ExpertDraftSelection] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def selected_updates(self) -> "SkillAction":
        if self.draft_updates and (self.action != "publish" or self.request_id is None):
            raise ValueError("所选草稿更新只能随发布并使用请求编号")
        if len({s.expert_id for s in self.draft_updates}) != len(self.draft_updates):
            raise ValueError("不能重复选择专家")
        return self


class SkillFileContent(BaseModel):
    path: str
    content: str


class SkillOverview(BaseModel):
    content: str


class SkillDistributionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    skill_id: UUID
    skill_name: str
    version: str
    actor_name: str
    source: str
    device_session_id: UUID | None = None
    client_version: str | None = None
    created_at: datetime


class SkillDistributionPage(BaseModel):
    items: list[SkillDistributionView]
    total: int
    page: int


class SkillImport(SkillMetadata):
    skill_id: UUID | None = None
    revision: int | None = None
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?$", max_length=50)
    release_notes: str = Field(default="", max_length=4000)
    package_base64: str = Field(max_length=28_000_000, repr=False)
