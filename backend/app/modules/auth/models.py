from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WebSession(Base):
    __tablename__ = "web_sessions"
    __table_args__ = (
        CheckConstraint("policy_mode IN ('strict', 'persistent')", name="web_session_policy_mode"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf: Mapped[str] = mapped_column(String(64))
    identity_id: Mapped[UUID | None] = mapped_column(ForeignKey("login_identities.id"))
    authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tokens: Mapped[str | None] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    policy_mode: Mapped[Literal["strict", "persistent"]] = mapped_column(
        String(20), default="strict", server_default="strict"
    )
    absolute_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    renewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requires_reauth: Mapped[bool] = mapped_column(default=False, server_default="false")
    setup_hash: Mapped[str | None] = mapped_column(String(64))
    invitation_id: Mapped[UUID | None] = mapped_column(ForeignKey("invitations.id"))
    invitation_hash: Mapped[str | None] = mapped_column(String(64))
    organization_invitation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organization_invitations.id")
    )
    organization_invitation_hash: Mapped[str | None] = mapped_column(String(64))
    organization_opening_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organization_openings.id")
    )
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"))
    # The hash of the newest attempt prevents stale callbacks replacing a newer login.
    login_state: Mapped[str | None] = mapped_column(String(64))
    login_data: Mapped[str | None] = mapped_column()
    login_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RateLimit(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int]
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrganizationOpeningFlow(Base):
    """Per-tab opening context; the ID never grants access without its browser session."""

    __tablename__ = "organization_opening_flows"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(
        ForeignKey("web_sessions.id", ondelete="CASCADE"), index=True
    )
    invitation_id: Mapped[UUID | None] = mapped_column(ForeignKey("organization_invitations.id"))
    invitation_hash: Mapped[str | None] = mapped_column(String(64))
    opening_id: Mapped[UUID | None] = mapped_column(ForeignKey("organization_openings.id"))
    organization_name: Mapped[str] = mapped_column(String(60), default="", server_default="")
    login_state: Mapped[str | None] = mapped_column(String(64), index=True)
    login_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
