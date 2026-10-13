"""Management credentials are independent of Web, desktop and resource credentials."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ManagementSession(Base):
    __tablename__ = "management_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identity_id: Mapped[UUID] = mapped_column(ForeignKey("login_identities.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(100), default="management:read")
    name: Mapped[str] = mapped_column(String(100))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManagementToken(Base):
    __tablename__ = "management_tokens"
    __table_args__ = (
        CheckConstraint("kind IN ('access', 'refresh')", name="management_token_kind"),
    )
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("management_sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[UUID | None] = mapped_column()
    response: Mapped[str | None] = mapped_column(Text)
    response_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    successor_hash: Mapped[str | None] = mapped_column(String(64))


class ManagementLogin(Base):
    __tablename__ = "management_logins"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state_hash: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(64))
    challenge: Mapped[str] = mapped_column(String(43))
    redirect_uri: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed: Mapped[bool] = mapped_column(default=False)
    cancelled: Mapped[bool] = mapped_column(default=False)
    code_hash: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("management_sessions.id"))
    response: Mapped[str | None] = mapped_column(Text)
    response_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
