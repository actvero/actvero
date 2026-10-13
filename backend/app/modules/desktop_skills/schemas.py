from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from app.modules.skills.categories import SkillCategory
from app.modules.skills.schemas import SkillFile, SkillIcon


class DesktopSkillVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: str
    sha256: str
    size: int = Field(description="原始 ZIP 字节数")
    published_at: datetime
    release_notes: str


class DesktopSkill(BaseModel):
    id: UUID
    name: str = Field(description="包内稳定标识，不随展示名称修改")
    display_name: str
    description: str
    category: SkillCategory
    icon: SkillIcon
    revision: int = Field(description="展示资料/范围/发布修订号，不等同于内容版本")
    current_version: DesktopSkillVersion


class DesktopSkillPage(BaseModel):
    items: list[DesktopSkill]
    total: int
    page: int
    page_size: Literal[20] = 20


class DesktopSkillDetail(DesktopSkill):
    recommended_version: DesktopSkillVersion | None = Field(
        default=None,
        description="access_version=2时单独返回推荐版本；current_version为本次精确读取版本",
    )
    version_state: Literal["current", "superseded"] | None = None
    update_available: bool | None = None
    skill_md: str = Field(
        description="SKILL.md 正文，已去除 YAML 元数据；完整源码通过 entrypoint 文件预览读取"
    )
    entrypoint: str = Field(description="ZIP 内 SKILL.md 的路径；父目录为安装根")
    files: list[SkillFile]


class DesktopSkillCategory(SkillCategory):
    count: int = Field(description="当前成员可获取的生效技能数；与目录使用相同的 q 搜索")


class SkillDownloadInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_version: Literal[1, 2] = Field(
        default=1, description="2允许有服务端资格的精确历史版本；1保持当前版规则"
    )
    expert_id: UUID | None = None
    expert_release_id: UUID | None = None
    version_id: UUID = Field(description="用户确认的精确版本 ID；不静默换版")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="详情中的包摘要")

    @model_validator(mode="after")
    def expert_pair(self) -> "SkillDownloadInput":
        if (self.expert_id is None) != (self.expert_release_id is None):
            raise ValueError("专家ID和精确发布ID必须同时提供")
        return self


class SkillAdoptInput(SkillDownloadInput):
    request_id: UUID
    access_version: Literal[2] = 2


class InstalledSkill(SkillDownloadInput):
    skill_id: UUID


class SkillUpdatesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    access_version: Literal[1, 2] = 1
    items: list[InstalledSkill] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique(self) -> "SkillUpdatesInput":
        if len({item.skill_id for item in self.items}) != len(self.items):
            raise ValueError("技能 ID 不能重复")
        return self


class SkillUpdateState(BaseModel):
    skill_id: UUID
    status: Literal["current", "update_available", "unavailable"]
    adopted_usable: bool | None = None
    adopted_state: Literal["current", "superseded", "unavailable"] | None = None
    update_available: bool | None = None
    skill: DesktopSkill | None = Field(
        default=None, description="可用时返回最新展示资料；不可用不暴露名称、版本或原因"
    )

    @model_serializer(mode="wrap")
    def legacy_shape(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        result = cast(dict[str, Any], handler(self))
        for field in ("adopted_usable", "adopted_state", "update_available"):
            if getattr(self, field) is None:
                result.pop(field, None)
        return result


class SkillUpdatesView(BaseModel):
    items: list[SkillUpdateState]
