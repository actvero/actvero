"""Management credentials are independent of Web, desktop and resource credentials."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ManagementSession(Base):
    __tablename__ = "management_sessions"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    identity_id: Mapped[UUID] = mapped_column(ForeignKey("login_identities.id"), index=True)
    client_id: Mapped[str] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(100), default="management:read")
    platform_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    authorized_org_ids: Mapped[list[str] | None] = mapped_column(JSON)
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
    scope: Mapped[str] = mapped_column(String(100), default="management:read")
    platform_permissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    target: Mapped[str] = mapped_column(String(20), default="organization")
    authorization_version: Mapped[int] = mapped_column(default=1)
    reauthenticate: Mapped[bool] = mapped_column(default=False)
    approved_identity_id: Mapped[UUID | None] = mapped_column(ForeignKey("login_identities.id"))
    authorized_org_ids: Mapped[list[str] | None] = mapped_column(JSON)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed: Mapped[bool] = mapped_column(default=False)
    cancelled: Mapped[bool] = mapped_column(default=False)
    code_hash: Mapped[str | None] = mapped_column(String(64))
    session_id: Mapped[UUID | None] = mapped_column(ForeignKey("management_sessions.id"))
    response: Mapped[str | None] = mapped_column(Text)
    response_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManagementCommand(Base):
    __tablename__ = "management_commands"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(250))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ManagementOAuthAttempt(Base):
    __tablename__ = "management_mcp_oauth_attempts"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("management_sessions.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"))
    service_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_services.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column()
    verifier: Mapped[str | None] = mapped_column(Text)
    authorization_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(60))
    pending_tokens: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
