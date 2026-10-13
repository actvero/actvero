from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.modules.experts.categories import CategoryId
from app.modules.experts.categories import ExpertCategory as ExpertCategory
from app.modules.experts.dependency_schemas import ExactSkillChange
from app.modules.skills.icons import uploaded_image
from app.modules.skills.schemas import SkillScope


class ExpertInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def no_null(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, str) and "\0" in value:
            raise ValueError("文本不能包含空字符")
        if isinstance(value, str):
            # Desktop JavaScript measures strings in UTF-16 code units.
            length = len(value.encode("utf-16-le")) // 2
            for limit in cls.model_fields[info.field_name or ""].metadata:
                maximum = getattr(limit, "max_length", None)
                if maximum is not None and length > maximum:
                    raise ValueError(f"文本最多 {maximum} 个 UTF-16 字符")
        return value


Identifier = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Version = Annotated[str, Field(max_length=30, pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]


class ExpertRequirement(ExpertInput):
    key: Identifier
    label: str = Field(min_length=1, max_length=120)
    required: StrictBool = True

    @field_validator("key")
    @classmethod
    def safe_key(cls, value: str) -> str:
        if value in {"__proto__", "constructor", "prototype"}:
            raise ValueError("依赖标识是保留名称")
        return value


class ExpertSkillRef(ExpertRequirement):
    skill_id: UUID
    version_id: UUID
    sha256: Digest
    load: Literal["always", "on_demand"] = "always"


class ConnectorToolPolicy(ExpertInput):
    tools: list[Annotated[str, Field(min_length=1, max_length=256)]] | None = Field(
        default=None,
        max_length=512,
        description="工具名称白名单。null 为兼容旧版、跟随连接器开放工具；[] 禁用全部工具。",
    )

    @field_validator("tools")
    @classmethod
    def unique_tools(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (len(set(value)) != len(value) or any("\0" in v for v in value)):
            raise ValueError("工具名称不能重复或含空字符")
        return value


class ExpertConnectorRef(ExpertRequirement, ConnectorToolPolicy):
    connector_id: UUID


class ExpertContent(ExpertInput):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    avatar: str = Field(default="", max_length=500000, repr=False)
    tags: list[Annotated[str, Field(min_length=1, max_length=30)]] = Field(
        default_factory=list, max_length=8
    )
    instructions: str = Field(default="", max_length=64000)
    conversation_starters: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        default_factory=list, max_length=6
    )
    skills: list[ExpertSkillRef] = Field(default_factory=list, max_length=32)
    connectors: list[ExpertConnectorRef] = Field(default_factory=list, max_length=32)

    @field_validator("avatar")
    @classmethod
    def avatar_image(cls, value: str) -> str:
        if value:
            uploaded_image(value)  # Validate without changing immutable content on read.
        return value

    @model_validator(mode="after")
    def unique(self) -> Self:
        for rows in (self.skills, self.connectors):
            if len({row.key for row in rows}) != len(rows):
                raise ValueError("同类依赖的标识不能重复")
        if len({r.skill_id for r in self.skills}) != len(self.skills) or len(
            {r.connector_id for r in self.connectors}
        ) != len(self.connectors):
            raise ValueError("同一能力不能重复引用")
        for values in (self.tags, self.conversation_starters):
            if any("\0" in v for v in values):
                raise ValueError("文本不能包含空字符")
        if any(len(v.encode("utf-16-le")) // 2 > 30 for v in self.tags) or any(
            len(v.encode("utf-16-le")) // 2 > 1000 for v in self.conversation_starters
        ):
            raise ValueError("标签或开场问题超过桌面字符限制")
        return self


class ManifestSkill(ExpertRequirement):
    load: Literal["always", "on_demand"]


class ExpertManifestV1(ExpertInput):
    """Portable wire schema matching desktop v1; categories live in the envelope."""

    schemaVersion: Literal[1]
    id: Identifier
    version: Version
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    avatar: str = Field(max_length=500000)
    category: Literal["general"] = "general"
    tags: list[Annotated[str, Field(min_length=1, max_length=30)]] = Field(max_length=8)
    instructions: str = Field(min_length=1, max_length=64000)
    conversationStarters: list[Annotated[str, Field(min_length=1, max_length=1000)]] = Field(
        max_length=6
    )
    skills: list[ManifestSkill] = Field(max_length=32)
    connectors: list[ExpertRequirement] = Field(max_length=32)


class PublishedSkillRef(ExpertInput):
    key: Identifier
    skill_id: UUID
    version_id: UUID
    sha256: Digest


class CapabilityProof(ExpertInput):
    contract: Digest
    behavior: Digest


class PublishedConnectorRef(ConnectorToolPolicy):
    reference_version: Literal[3] | None = None
    capability_contracts: (
        dict[
            Literal["tools", "prompts", "resources", "templates"],
            dict[str, CapabilityProof],
        ]
        | None
    ) = Field(
        default=None,
        description="四类 kind+key 精确证明；旧发布缺省，须按新版协商识别未验证。",
    )
    tool_contracts: dict[str, Digest] | None = Field(
        default=None,
        max_length=512,
        description="选用工具的语义定义摘要。旧发布缺省表示未锁定，不能当作验证通过。",
    )
    key: Identifier
    connector_id: UUID


class ExpertDependencyRefs(ExpertInput):
    skills: list[PublishedSkillRef]
    connectors: list[PublishedConnectorRef]


class ExpertSave(ExpertInput):
    content: ExpertContent
    category: CategoryId = "uncategorized"


class ExpertUpdate(ExpertSave):
    revision: int = Field(ge=1)


class ExpertRevision(ExpertInput):
    revision: int = Field(ge=1)


class ExpertPublish(ExpertRevision):
    version: Version
    release_notes: str = Field(default="", max_length=4000)


class ExpertScope(SkillScope, ExpertRevision):
    pass


class ExpertReleaseView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: str
    sha256: str
    release_notes: str
    publisher_name: str
    created_at: datetime


class ExpertDependencyState(BaseModel):
    kind: Literal["skills", "connectors"]
    key: str
    label: str
    required: bool
    status: Literal["available", "unavailable", "version_conflict", "unverified"]
    missing_members: int = 0
    update_available: bool = False
    locked_version: str | None = None


class ExpertCheck(BaseModel):
    can_publish: bool
    instruction_missing: bool
    audience_count: int
    dependencies: list[ExpertDependencyState]


class ExpertSummary(BaseModel):
    id: UUID
    name: str
    description: str
    avatar: str
    category: ExpertCategory
    audience: Literal["administrators", "selected", "organization"]
    revision: int
    metadata_revision: int
    current_release: ExpertReleaseView | None
    has_changes: bool
    dependency_issues: int = 0
    status: Literal["draft", "published", "withdrawn"]


class ExpertView(ExpertSummary):
    content: ExpertContent
    member_ids: list[UUID]
    releases: list[ExpertReleaseView]
    check: ExpertCheck


class ExpertPage(BaseModel):
    items: list[ExpertSummary]
    total: int
    page: int
    page_size: int = 20


class ExpertSkillImpact(BaseModel):
    id: UUID
    name: str
    version: str
    revision: int = 1
    current_release_id: UUID | None = None
    draft_changes: list[ExactSkillChange] = Field(default_factory=list)
    draft_versions: list[str] = Field(default_factory=list)
    published_versions: list[str] = Field(default_factory=list)


class ExpertSkillImpactView(BaseModel):
    items: list[ExpertSkillImpact]
    total: int
    page: int = 1
    page_size: int = 20


class ExpertToolOption(BaseModel):
    key: str
    name: str
    description: str
    enabled: bool


class ExpertDependencyOption(BaseModel):
    id: UUID
    name: str
    description: str
    version_id: UUID | None = None
    version: str = ""
    sha256: str = ""
    icon: str = ""
    status: Literal["available", "unavailable", "version_conflict"] = "available"
    tools: list[ExpertToolOption] = Field(default_factory=list)
    tools_discovered: bool = False
    update_available: bool = False


class ExpertDependencyPage(BaseModel):
    items: list[ExpertDependencyOption]
    total: int
    page: int
    page_size: int = 20
