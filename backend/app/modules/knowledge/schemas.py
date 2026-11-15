from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.modules.departments.schemas import DepartmentGrant
from app.modules.skills.schemas import SkillIconSelection, SkillIconSelectionView


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Chunking(Input):
    structure: Literal["general", "parent_child"] = "general"
    mode: Literal["smart", "normal"] = "smart"
    target_chars: int = Field(default=1200, ge=100, le=6000, description="智能切片目标字数")
    max_chars: int = Field(
        default=1800,
        ge=100,
        le=10000,
        description="智能模式的合并软上限；长度模式的切片长度，均受模型输入硬上限约束",
    )
    overlap_chars: int = Field(default=100, ge=0, le=1000, description="长度切片的重叠字数")
    child_chars: int = Field(default=350, ge=50, le=2000, description="子片长度上限")

    @model_validator(mode="after")
    def valid(self) -> "Chunking":
        if self.mode == "smart" and self.max_chars < self.target_chars:
            raise ValueError("合并上限须不小于目标字数")
        if self.structure == "parent_child" and self.child_chars >= self.max_chars:
            raise ValueError("子片长度须小于父片上限")
        window = self.child_chars if self.structure == "parent_child" else self.max_chars
        if self.mode == "normal" and self.overlap_chars >= window:
            raise ValueError("重叠长度须小于切片长度")
        return self


class RetrievalPolicy(Input):
    mode: Literal["keyword", "vector", "hybrid"] = "keyword"
    embedding_model_id: UUID | None = None
    rerank_model_id: UUID | None = None
    vector_weight: int = Field(default=50, ge=1, le=99, description="混合检索中向量排名权重百分比")

    @model_validator(mode="after")
    def valid(self) -> "RetrievalPolicy":
        if self.mode == "keyword":
            self.embedding_model_id = None
        elif not self.embedding_model_id:
            raise ValueError("向量检索和混合检索需要选择向量模型")
        return self


class KnowledgeFields(Input):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    audience: Literal["administrators", "organization", "selected"] = "administrators"
    member_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    department_grants: list[DepartmentGrant] = Field(default_factory=list, max_length=100)
    chunking: Chunking = Field(default_factory=Chunking)


class KnowledgeWrite(KnowledgeFields):
    icon_selection: SkillIconSelection | None = Field(
        default=None, description="新建时可不设头像；更新时省略则保留原头像，auto 移除头像"
    )


class KnowledgeCreate(KnowledgeWrite):
    retrieval: RetrievalPolicy | None = None
    defaults_version: int | None = Field(default=None, ge=0)


class KnowledgeUpdate(KnowledgeWrite):
    retrieval: RetrievalPolicy | None = None
    version: int = Field(ge=1)


class KnowledgeIconUpdate(Input):
    version: int = Field(ge=1)
    icon_selection: SkillIconSelection


class KnowledgeView(KnowledgeFields):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    icon: SkillIconSelectionView = Field(
        default_factory=SkillIconSelectionView, description="头像来源及可直接展示的图片"
    )
    embedding_profile: dict[str, Any]
    retrieval: RetrievalPolicy
    document_count: int = 0
    status: str = "empty"
    updated_at: datetime
    can_manage: bool = False


class KnowledgePage(BaseModel):
    items: list[KnowledgeView]
    total: int


class CredentialCreate(Input):
    name: str = Field(min_length=1, max_length=100)
    account: str = Field(min_length=1, max_length=100, description="同一官方账号使用相同标记")
    key: str = Field(min_length=10, max_length=4096, json_schema_extra={"writeOnly": True})


class CredentialRename(Input):
    name: str = Field(min_length=1, max_length=100)


class CredentialView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    account: str
    enabled: bool
    cooldown_until: datetime | None
    error: str


class CredentialBatchCreate(Input):
    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=97,
        description="可选名称，新增多个 Key 时在名称后编号",
    )
    keys: list[Annotated[SecretStr, Field(min_length=10, max_length=4096)]] = Field(
        min_length=1, max_length=20, description="批量添加 Key，重复项自动忽略"
    )


class KnowledgeDefaults(Input):
    version: int = Field(default=0, ge=0)
    embedding_model_id: UUID | None = None
    rerank_model_id: UUID | None = None
    rerank_enabled: bool = False


class ModelOption(BaseModel):
    id: UUID
    name: str
    kind: str
    dimensions: int | None


class KnowledgeDefaultsView(KnowledgeDefaults):
    credentials: list[CredentialView]
    models: list[ModelOption]


class DocumentView(BaseModel):
    id: UUID
    filename: str
    media_type: str
    size: int
    created_at: datetime
    generation_id: UUID | None
    active_generation_id: UUID | None
    status: str
    error: str
    chunk_count: int
    indexed_count: int
    chunk_structure: Literal["general", "parent_child"] | None = None
    character_count: int | None = None


class SourceLocation(BaseModel):
    block_id: str
    page: int | None = None
    bbox: list[float] | None = None
    coordinate_space: Literal["normalized", "page", "unknown"] = "unknown"
    page_width: float | None = None
    page_height: float | None = None
    start: int = 0
    end: int = 0
    heading: str = ""
    line: int | None = None
    sheet: str | None = None
    cell_range: str | None = None


class ChunkView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence: int
    content: str
    sources: list[SourceLocation]
    parent_id: UUID | None = None


class DocumentDetail(DocumentView):
    chunks: list[ChunkView]
    total_chunks: int
    can_manage: bool
    source_url: str
    chunking: Chunking | None = None


class RebuildInput(Input):
    generation_id: UUID
    chunking: Chunking | None = None
    use_current_defaults: bool = False
    preview_token: str | None = Field(default=None, min_length=64, max_length=64)


class RetrievalInput(Input):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)
    rerank: bool | None = None


class CitationView(BaseModel):
    id: UUID
    base_id: UUID
    document_id: UUID
    generation_id: UUID
    filename: str
    content: str
    sources: list[SourceLocation]
    source_url: str


class ParentContext(BaseModel):
    id: UUID
    content: str


class RetrievalHit(CitationView):
    score: float
    parent_context: ParentContext | None = None


class RetrievalView(BaseModel):
    mode: Literal["hybrid", "keyword", "vector"]
    reranked: bool
    items: list[RetrievalHit]


class SourceBlock(SourceLocation):
    text: str
    type: str = "text"


class ParsedSource(BaseModel):
    blocks: list[SourceBlock]
    total: int
    offset: int


class OriginalTextRange(BaseModel):
    start: int = Field(ge=0, description="原件 Unicode 字符起点，不是 UTF-16 偏移")
    end: int = Field(ge=0, description="原件 Unicode 字符终点，不包含此字符")


class ChunkPreviewInput(Input):
    generation_id: UUID
    chunking: Chunking
    page: int = Field(default=1, ge=1)
    query: str = Field(default="", max_length=200)


class ChunkPreviewItem(BaseModel):
    sequence: int
    content: str
    sources: list[SourceLocation]
    text_ranges: list[OriginalTextRange] = Field(default_factory=list)
    parent_sequence: int | None = None
    parent_content: str | None = None


class ChunkPreviewView(BaseModel):
    generation_id: UUID
    chunking: Chunking
    preview_token: str
    chunks: list[ChunkPreviewItem]
    total_chunks: int
    filtered_total: int
    parent_count: int
    average_chars: int
    shortest_chars: int
    longest_chars: int
    model_limit: int


class DocumentPreview(BaseModel):
    document_id: UUID
    generation_id: UUID | None
    filename: str
    media_type: str
    source_url: str
    sources: list[SourceLocation] = Field(default_factory=list)
    text_ranges: list[OriginalTextRange] = Field(default_factory=list)
    citation_id: UUID | None = None


class ReaderSessionInput(Input):
    parent_origin: str = Field(
        max_length=300, description="嵌入方的完整 HTTPS origin；本地开发允许 HTTP localhost"
    )


class ReaderSessionView(BaseModel):
    viewer_url: str = Field(description="无秘密的独立阅读器地址，可放入任意宿主容器")
    token: str = Field(description="短期、单文档凭证，仅经 postMessage 传入，不放入 URL")
    expires_at: datetime
    parent_origin: str
    protocol: Literal["actvero.knowledge.v1"] = "actvero.knowledge.v1"
