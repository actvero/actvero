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
        CheckConstraint("mode IN ('limited', 'unlimited')"),
        CheckConstraint(
            "(mode = 'unlimited' AND jsonb_array_length(rules) = 0) OR "
            "(mode = 'limited' AND jsonb_array_length(rules) > 0)"
        ),
        CheckConstraint("NOT is_default OR NOT archived"),
        Index(
            "uq_quota_default",
            "tenant_id",
            unique=True,
            postgresql_where=text("is_default AND NOT archived"),
        ),
        Index(
            "uq_quota_name", "tenant_id", "name", unique=True, postgresql_where=text("NOT archived")
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    is_default: Mapped[bool] = mapped_column(default=False)
    mode: Mapped[str] = mapped_column(String(16), default="limited")
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    archived: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotaAssignment(Base):
    __tablename__ = "quota_assignments"
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    policy_id: Mapped[UUID | None] = mapped_column(ForeignKey("quota_policies.id"), index=True)
    version: Mapped[int] = mapped_column(default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
