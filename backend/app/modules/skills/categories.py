"""Organization-owned categories. Seed labels are defaults, never a runtime enum."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.skills.models import SkillCategoryRecord

CategoryId = Annotated[str, Field(min_length=1, max_length=36, pattern=r"^[a-z0-9-]+$")]
DEFAULT_CATEGORIES = (
    ("office", "办公协同"),
    ("development", "开发工具"),
    ("data", "数据分析"),
    ("content", "内容创作"),
    ("design", "设计创意"),
    ("research", "知识检索"),
    ("productivity", "效率工具"),
    ("other", "其他"),
    ("uncategorized", "未分类"),
)


class SkillCategory(BaseModel):
    id: CategoryId
    name: str


class ManagedSkillCategory(SkillCategory):
    count: int
    revision: int
    system: bool


class CategoryName(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=30)

    @field_validator("name", mode="before")
    @classmethod
    def trim(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class CategoryRename(CategoryName):
    revision: int = Field(ge=1)


class CategoryMove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    direction: Literal["up", "down"]


class CategoryDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    count: int = Field(ge=0, description="确认时的技能数量；变化时返回 409")
    target_id: CategoryId = "uncategorized"


def seed_categories(db: AsyncSession, tenant_id: UUID) -> None:
    db.add_all(
        [
            SkillCategoryRecord(
                tenant_id=tenant_id, id=key, name=name, name_key=name.casefold(), position=i
            )
            for i, (key, name) in enumerate(DEFAULT_CATEGORIES)
        ]
    )


async def category_rows(db: AsyncSession, tenant_id: UUID) -> list[SkillCategoryRecord]:
    return list(
        await db.scalars(
            select(SkillCategoryRecord)
            .where(SkillCategoryRecord.tenant_id == tenant_id)
            .order_by(
                SkillCategoryRecord.id == "uncategorized",
                SkillCategoryRecord.position,
                SkillCategoryRecord.id,
            )
        )
    )


async def require_category(db: AsyncSession, tenant_id: UUID, key: str) -> SkillCategoryRecord:
    row = await db.get(SkillCategoryRecord, (tenant_id, key))
    if row is None:
        raise HTTPException(422, "类别已删除或不存在，请刷新后重新选择")
    return row


def category_view(row: SkillCategoryRecord) -> SkillCategory:
    return SkillCategory(id=row.id, name=row.name)
