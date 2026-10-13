from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint("role IN ('administrator', 'member')"),
        CheckConstraint("status IN ('active', 'paused', 'removed')"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    status: Mapped[str] = mapped_column(String(20), default="active")
    source: Mapped[str] = mapped_column(String(20))
    version: Mapped[int] = mapped_column(default=1)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        Index(
            "uq_pending_invitation",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        CheckConstraint("status IN ('pending', 'accepted', 'revoked', 'expired')"),
        CheckConstraint("role IN ('administrator', 'member')"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str | None] = mapped_column(String(255))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_ciphertext: Mapped[str | None] = mapped_column(String(1000))
    role: Mapped[str] = mapped_column(String(20), default="member", server_default="member")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    mail_status: Mapped[str] = mapped_column(String(20), default="pending")
    needs_activation: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    accepted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_delivery_request_id: Mapped[UUID | None]


class MemberCreation(Base):
    """Durable provisioning correlation; never stores a password."""

    __tablename__ = "member_creations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        CheckConstraint("role IN ('administrator', 'member')"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"))
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20))
    marker: Mapped[str] = mapped_column(String(64))
    member_id: Mapped[UUID | None] = mapped_column(ForeignKey("memberships.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
