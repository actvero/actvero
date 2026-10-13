from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QuotaPolicy(Base):
    __tablename__ = "quota_policies"
    __table_args__ = (
        CheckConstraint("priority >= 0 AND priority <= 1000000"),
        CheckConstraint("priority <> 0 OR NOT archived"),
        Index(
            "uq_quota_priority",
            "tenant_id",
            "priority",
            unique=True,
            postgresql_where=text("NOT archived"),
        ),
        Index(
            "uq_quota_name", "tenant_id", "name", unique=True, postgresql_where=text("NOT archived")
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    priority: Mapped[int]
    member_ids: Mapped[list[str]] = mapped_column(JSONB)
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    archived: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
