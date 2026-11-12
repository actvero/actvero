from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(
            ["tenant_id", "parent_id"], ["departments.tenant_id", "departments.id"]
        ),
        Index("ix_departments_tenant_parent", "tenant_id", "parent_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    parent_id: Mapped[UUID | None] = mapped_column()
    name: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(default=1)


class DepartmentMember(Base):
    __tablename__ = "department_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"]
        ),
        Index("ix_department_members_tenant_department", "tenant_id", "department_id"),
        Index(
            "uq_department_members_primary",
            "member_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    member_id: Mapped[UUID] = mapped_column(
        ForeignKey("memberships.id", ondelete="CASCADE"), primary_key=True
    )
    department_id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column()
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
