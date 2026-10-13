"""Short-lived resource authority and device-bound upstream OAuth attempts."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ResourceToken(Base):
    __tablename__ = "desktop_resource_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("device_sessions.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"))
    resource: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class NativeOAuthAttempt(Base):
    __tablename__ = "desktop_mcp_oauth_attempts"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("device_sessions.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"))
    service_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_services.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column()
    verifier: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(60))
    pending_tokens: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
