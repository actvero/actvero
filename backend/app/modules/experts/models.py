from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.service import now


class ExpertCategoryRecord(Base):
    __tablename__ = "expert_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name_key"),)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(30))
    name_key: Mapped[str] = mapped_column(String(90))
    position: Mapped[int] = mapped_column()
    revision: Mapped[int] = mapped_column(default=1)


class ExpertRecord(Base):
    __tablename__ = "experts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "category"],
            ["expert_categories.tenant_id", "expert_categories.id"],
            name="fk_experts_category",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500))
    category: Mapped[str] = mapped_column(String(36), default="uncategorized")
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB)
    audience: Mapped[str] = mapped_column(String(20), default="administrators")
    member_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    current_release_id: Mapped[UUID | None] = mapped_column(nullable=True)
    revision: Mapped[int] = mapped_column(default=1)
    metadata_revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ExpertRelease(Base):
    """Immutable content; visibility is controlled by the expert's current pointer."""

    __tablename__ = "expert_releases"
    __table_args__ = (UniqueConstraint("expert_id", "version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    expert_id: Mapped[UUID] = mapped_column(ForeignKey("experts.id"), index=True)
    version: Mapped[str] = mapped_column(String(30))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSONB)
    dependency_refs: Mapped[dict[str, Any]] = mapped_column(JSONB)
    sha256: Mapped[str] = mapped_column(String(64))
    release_notes: Mapped[str] = mapped_column(Text, default="")
    publisher_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DependencyCommandReceipt(Base):
    """Member-scoped receipts contain no draft contents or secrets."""

    __tablename__ = "dependency_command_receipts"
    __table_args__ = (UniqueConstraint("member_id", "request_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"), index=True)
    request_id: Mapped[UUID] = mapped_column()
    fingerprint: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(40))
    resource_id: Mapped[UUID] = mapped_column()
    updated_experts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
