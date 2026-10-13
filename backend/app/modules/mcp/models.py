"""Service policy is shared; discovery and credentials are identity-scoped."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.service import now


class McpService(Base):
    __tablename__ = "mcp_services"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    display_name: Mapped[str] = mapped_column(String(100), default="")
    icon: Mapped[str] = mapped_column(Text, default="")
    examples: Mapped[list[str]] = mapped_column(JSONB, default=list)
    transport: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(String(2000), default="")
    enabled: Mapped[bool] = mapped_column(default=False)
    catalog_initialized: Mapped[bool] = mapped_column(default=False)
    audience: Mapped[str] = mapped_column(String(20), default="organization")
    member_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    auth_mode: Mapped[str] = mapped_column(String(20), default="none")
    credential_fields: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    oauth: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    connection_options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class McpConnection(Base):
    __tablename__ = "mcp_connections"
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_services.id", ondelete="CASCADE"), primary_key=True
    )
    # Zero UUID denotes explicitly configured organization credentials, never a fallback.
    owner_id: Mapped[UUID] = mapped_column(primary_key=True)
    sealed: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class McpSnapshot(Base):
    __tablename__ = "mcp_snapshots"
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_services.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[UUID] = mapped_column(primary_key=True)
    capabilities: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    protocol: Mapped[str] = mapped_column(String(100), default="")
    negotiated: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(200))


class McpPolicy(Base):
    __tablename__ = "mcp_capability_policies"
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_services.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    key: Mapped[str] = mapped_column(String(2000), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str | None] = mapped_column(Text)
    definition_hash: Mapped[str] = mapped_column(String(64), default="")


class McpContent(Base):
    __tablename__ = "mcp_contents"
    __table_args__ = (UniqueConstraint("service_id", "kind", "name"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_services.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text)
    arguments: Mapped[list[str]] = mapped_column(JSONB, default=list)
    mime_type: Mapped[str] = mapped_column(String(100), default="text/plain")
    enabled: Mapped[bool] = mapped_column(default=False)


class McpOAuthAttempt(Base):
    __tablename__ = "mcp_oauth_attempts"
    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    service_id: Mapped[UUID] = mapped_column(ForeignKey("mcp_services.id", ondelete="CASCADE"))
    session_id: Mapped[UUID] = mapped_column(ForeignKey("web_sessions.id", ondelete="CASCADE"))
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"))
    version: Mapped[int] = mapped_column()
    verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class McpActivity(Base):
    __tablename__ = "mcp_activities"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    service_id: Mapped[UUID] = mapped_column(index=True)
    service_name: Mapped[str] = mapped_column(String(100))
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    actor_name: Mapped[str] = mapped_column(String(200))
    owner_id: Mapped[UUID] = mapped_column()
    category: Mapped[str] = mapped_column(String(20), index=True)
    operation: Mapped[str] = mapped_column(String(40))
    capability: Mapped[str] = mapped_column(String(2000), default="")
    source: Mapped[str] = mapped_column(String(20), default="console")
    device_session_id: Mapped[UUID | None] = mapped_column(nullable=True)
    access_key_id: Mapped[UUID | None] = mapped_column(ForeignKey("access_keys.id"), index=True)
    client_version: Mapped[str] = mapped_column(String(50), default="")
    result: Mapped[str] = mapped_column(String(20))
    duration_ms: Mapped[int] = mapped_column()
    error_code: Mapped[str] = mapped_column(String(40), default="")
    message: Mapped[str] = mapped_column(String(200), default="")
    request_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class McpHealth(Base):
    __tablename__ = "mcp_health"
    service_id: Mapped[UUID] = mapped_column(
        ForeignKey("mcp_services.id", ondelete="CASCADE"), primary_key=True
    )
    owner_id: Mapped[UUID] = mapped_column(primary_key=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    error: Mapped[str | None] = mapped_column(String(200))
    failures: Mapped[int] = mapped_column(default=0)
