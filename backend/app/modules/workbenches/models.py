from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.service import now


class Workbench(Base):
    __tablename__ = "workbenches"
    __table_args__ = (UniqueConstraint("tenant_id", "package_name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    package_name: Mapped[str] = mapped_column(String(214))
    display_name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(20), default="uncategorized")
    audience: Mapped[str] = mapped_column(String(20), default="administrators")
    member_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    department_grants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    config_values: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    revision: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkbenchVersion(Base):
    __tablename__ = "workbench_versions"
    __table_args__ = (
        UniqueConstraint("workbench_id", "version"),
        Index(
            "uq_workbench_versions_one_published",
            "workbench_id",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workbench_id: Mapped[UUID] = mapped_column(
        ForeignKey("workbenches.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    dsh_requirement: Mapped[str] = mapped_column(String(160))
    size: Mapped[int] = mapped_column()
    sha256: Mapped[str] = mapped_column(String(64))
    release_notes: Mapped[str] = mapped_column(Text, default="")
    uploader_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    icon_data_url: Mapped[str | None] = mapped_column(Text)
    preview_data_urls: Mapped[list[str] | None] = mapped_column(JSONB)


class WorkbenchPackage(Base):
    """Original package bytes are read separately from version listings."""

    __tablename__ = "workbench_packages"

    version_id: Mapped[UUID] = mapped_column(
        ForeignKey("workbench_versions.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[bytes] = mapped_column(LargeBinary)
