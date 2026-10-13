from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeviceSession(Base):
    __tablename__ = "device_sessions"
    __table_args__ = (
        CheckConstraint(
            "policy_mode IN ('strict', 'persistent')", name="device_session_policy_mode"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identity_id: Mapped[UUID] = mapped_column(ForeignKey("login_identities.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(100), default="desktop:self")
    name: Mapped[str] = mapped_column(String(100))
    os: Mapped[str] = mapped_column(String(20))
    app_version: Mapped[str] = mapped_column(String(50))
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    policy_mode: Mapped[Literal["strict", "persistent"]] = mapped_column(
        String(20), default="strict", server_default="strict"
    )
    absolute_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceToken(Base):
    __tablename__ = "device_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("device_sessions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    request_id: Mapped[UUID | None] = mapped_column()
    response: Mapped[str | None] = mapped_column(Text)
    response_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    successor_hash: Mapped[str | None] = mapped_column(String(64))


class DesktopLogin(Base):
    __tablename__ = "desktop_logins"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    state_hash: Mapped[str] = mapped_column(String(64))
    nonce: Mapped[str] = mapped_column(String(64))
    challenge: Mapped[str] = mapped_column(String(43))
    redirect_uri: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(100))
    os: Mapped[str] = mapped_column(String(20))
    app_version: Mapped[str] = mapped_column(String(50))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed: Mapped[bool] = mapped_column(default=False)
    cancelled: Mapped[bool] = mapped_column(default=False)
    code_hash: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("device_sessions.id"))
    response: Mapped[str | None] = mapped_column(Text)
    response_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ResourceAdoption(Base):
    """Server proof of an explicit choice, never a replacement for live permissions."""

    __tablename__ = "resource_adoptions"
    __table_args__ = (
        UniqueConstraint("member_id", "request_id"),
        CheckConstraint("kind IN ('skills', 'experts')", name="resource_adoption_kind"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"), index=True)
    request_id: Mapped[UUID] = mapped_column()
    kind: Mapped[str] = mapped_column(String(20))
    resource_id: Mapped[UUID] = mapped_column(index=True)
    version_id: Mapped[UUID] = mapped_column(index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    device_session_id: Mapped[UUID] = mapped_column(ForeignKey("device_sessions.id"))
    expert_id: Mapped[UUID | None] = mapped_column()
    expert_release_id: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
