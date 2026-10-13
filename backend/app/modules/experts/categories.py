"""Organization-owned categories. Seed labels are defaults, never a runtime enum."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.experts.models import ExpertCategoryRecord

CategoryId = Annotated[str, Field(min_length=1, max_length=36, pattern=r"^[a-z0-9-]+$")]
DEFAULT_CATEGORIES = (
    ("office", "办公协同"),
    ("engineering", "工程开发"),
    ("design", "设计创意"),
    ("content", "内容创作"),
    ("data", "数据分析"),
    ("education", "教育学习"),
    ("lifestyle", "生活服务"),
    ("general", "通用"),
    ("uncategorized", "未分类"),
)


class ExpertCategory(BaseModel):
    id: CategoryId
    name: str


class ManagedExpertCategory(ExpertCategory):
    count: int
    revision: int
    system: bool


class ExpertCategoryName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=30)

    @field_validator("name", mode="before")
    @classmethod
    def trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ExpertCategoryRename(ExpertCategoryName):
    revision: int = Field(ge=1)


class ExpertCategoryMove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    direction: Literal["up", "down"]


class ExpertCategoryDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    count: int = Field(ge=0, description="确认时的专家数量；变化时返回 409")
    target_id: CategoryId = "uncategorized"


def seed_categories(db: AsyncSession, tenant_id: UUID) -> None:
    db.add_all(
        [
            ExpertCategoryRecord(
                tenant_id=tenant_id, id=key, name=name, name_key=name.casefold(), position=i
            )
            for i, (key, name) in enumerate(DEFAULT_CATEGORIES)
        ]
    )


async def category_rows(db: AsyncSession, tenant_id: UUID) -> list[ExpertCategoryRecord]:
    return list(
        await db.scalars(
            select(ExpertCategoryRecord)
            .where(ExpertCategoryRecord.tenant_id == tenant_id)
            .order_by(
                ExpertCategoryRecord.id == "uncategorized",
                ExpertCategoryRecord.position,
                ExpertCategoryRecord.id,
            )
        )
    )


async def require_category(db: AsyncSession, tenant_id: UUID, key: str) -> ExpertCategoryRecord:
    row = await db.get(ExpertCategoryRecord, (tenant_id, key))
    if row is None:
        raise HTTPException(422, "类别已删除或不存在，请刷新后重新选择")
    return row


def category_view(row: ExpertCategoryRecord) -> ExpertCategory:
    return ExpertCategory(id=row.id, name=row.name)
