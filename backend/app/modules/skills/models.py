from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.modules.auth.service import now


class SkillCategoryRecord(Base):
    __tablename__ = "skill_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name_key"),)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    name_key: Mapped[str] = mapped_column(String(90))
    position: Mapped[int] = mapped_column()
    revision: Mapped[int] = mapped_column(default=1)


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        ForeignKeyConstraint(
            ["tenant_id", "category"],
            ["skill_categories.tenant_id", "skill_categories.id"],
            name="fk_skills_category",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(36), default="uncategorized")
    category_info: Mapped[SkillCategoryRecord] = relationship(lazy="joined", viewonly=True)
    icon_selection: Mapped[dict[str, str]] = mapped_column(
        JSONB, default=lambda: {"source": "auto"}
    )
    audience: Mapped[str] = mapped_column(String(20))
    member_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    default_version_id: Mapped[UUID | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SkillVersion(Base):
    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version"),
        Index(
            "uq_skill_versions_one_published",
            "skill_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    skill_id: Mapped[UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True)
    version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    release_notes: Mapped[str] = mapped_column(Text, default="")
    uploader_name: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column()
    files: Mapped[list[dict[str, str | int | bool]]] = mapped_column(JSONB)
    skill_md: Mapped[str] = mapped_column(Text)
    package_icon: Mapped[str] = mapped_column(Text, default="")
    icon_warning: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SkillPackage(Base):
    """Original immutable ZIP, separate from publication/authorization metadata."""

    __tablename__ = "skill_packages"
    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("skill_versions.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)


class SkillDistribution(Base):
    __tablename__ = "skill_distributions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    skill_id: Mapped[UUID] = mapped_column(index=True)
    skill_name: Mapped[str] = mapped_column(String(100))
    version: Mapped[str] = mapped_column(String(50))
    actor_id: Mapped[UUID] = mapped_column()
    actor_name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), default="console")
    device_session_id: Mapped[UUID | None] = mapped_column(nullable=True)
    client_version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
