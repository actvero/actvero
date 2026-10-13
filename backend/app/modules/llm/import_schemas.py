from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.modules.llm.catalog_schemas import OperationKind
from app.modules.llm.schemas import Input, ModelHint


class ImportItem(Input):
    upstream_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,199}$")
    action: Literal["create", "link", "skip"] = "create"
    slug: str | None = Field(default=None, max_length=200)
    name: str | None = Field(default=None, max_length=100)
    kinds: list[OperationKind] | None = Field(default=None, max_length=6)
    target_id: UUID | None = None

    @model_validator(mode="after")
    def unique_kinds(self) -> Self:
        if self.kinds is not None and len(self.kinds) != len(set(self.kinds)):
            raise ValueError("接口不能重复")
        return self


class ImportInput(Input):
    channel_id: UUID
    channel_version: int = Field(ge=1)
    items: list[ImportItem] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_sources(self) -> Self:
        ids = [item.upstream_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("同批上游模型不能重复")
        return self


class ImportPreviewItem(ImportItem):
    hint: ModelHint
    target_version: int | None = None
    status: Literal["create", "link", "unchanged", "skip", "error"]
    errors: list[str] = Field(default_factory=list)
    added_bindings: int = 0


class ImportPreview(BaseModel):
    revision: str
    items: list[ImportPreviewItem]
    create_count: int
    link_count: int
    binding_count: int
    can_commit: bool


class ImportCommit(ImportInput):
    request_id: UUID
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImportResultItem(BaseModel):
    upstream_id: str
    model_id: UUID | None = None
    slug: str | None = None
    status: Literal["created", "linked", "unchanged", "skipped"]
    added_bindings: int = 0


class ImportResult(BaseModel):
    request_id: UUID
    items: list[ImportResultItem]


class ImportStatus(BaseModel):
    committed: bool
    result: ImportResult | None = None
