from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (CheckConstraint("instance_slot = 1"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # SaaS migrations remove the legacy constraint; community deployments keep
    # it as a second line of defense.
    instance_slot: Mapped[int] = mapped_column(default=1, server_default="1", unique=True)
    name: Mapped[str] = mapped_column(String(60))
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Installation(Base):
    __tablename__ = "installation"
    __table_args__ = (CheckConstraint("id = 1"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[UUID] = mapped_column(
        default=uuid4, server_default=text("gen_random_uuid()")
    )
    branding_revision: Mapped[UUID] = mapped_column(
        default=uuid4, server_default=text("gen_random_uuid()")
    )
    issuer: Mapped[str | None] = mapped_column(String(500))
    subject: Mapped[str | None] = mapped_column(String(255))
    organization_name: Mapped[str | None] = mapped_column(String(60))
    registration_marker: Mapped[str | None] = mapped_column(String(64))
    # Legacy expiry is retained for data-preserving upgrades; it no longer gates setup.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tenant_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"))
    platform_operator_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    # Optional SaaS branding. Empty values deliberately fall back to the
    # product defaults so a fresh deployment never needs a branding wizard.
    platform_name: Mapped[str | None] = mapped_column(String(80))
    platform_logo_url: Mapped[str | None] = mapped_column(String(2048))
    platform_logo_data: Mapped[bytes | None] = mapped_column(LargeBinary)
    platform_logo_version: Mapped[UUID | None] = mapped_column()
    branding_assets: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    identity_branding_revision: Mapped[UUID | None] = mapped_column()
    platform_mail_ciphertext: Mapped[str | None] = mapped_column(Text)
    portal_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    # None preserves the deployment default until a platform operator saves a choice.
    management_enabled: Mapped[bool | None] = mapped_column()
    registration_mode: Mapped[str] = mapped_column(
        String(20), default="invite", server_default="invite"
    )
    invitation_verify_email: Mapped[bool] = mapped_column(default=False, server_default="false")


class BrandAsset(Base):
    """Immutable deployment brand images retained for existing public references."""

    __tablename__ = "brand_assets"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    data: Mapped[bytes] = mapped_column(LargeBinary)
    media_type: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlatformOperator(Base):
    """A deployment-scoped operator; separate from organization membership."""

    __tablename__ = "platform_operators"
    __table_args__ = (CheckConstraint("status IN ('active', 'paused')"),)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OrganizationInvitation(Base):
    """A one-time link used to initialize a new SaaS organization."""

    __tablename__ = "organization_invitations"
    __table_args__ = (CheckConstraint("status IN ('pending', 'accepted', 'revoked', 'expired')"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"))
    organization_name: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(100))
    subject: Mapped[str | None] = mapped_column(String(255))
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    needs_activation: Mapped[bool] = mapped_column(default=False, server_default="false")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_ciphertext: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))


class OrganizationOpening(Base):
    """Registration correlation and opening decisions, never credentials."""

    __tablename__ = "organization_openings"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'pending', 'approved', 'rejected', 'completed')"),
        CheckConstraint("mode IN ('invite', 'approval', 'self_service')"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    invitation_id: Mapped[UUID | None] = mapped_column(ForeignKey("organization_invitations.id"))
    mode: Mapped[str] = mapped_column(String(20))
    organization_name: Mapped[str] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(320))
    subject: Mapped[str | None] = mapped_column(String(255))
    registration_marker: Mapped[str | None] = mapped_column(String(64))
    applicant_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", server_default="draft")
    organization_id: Mapped[UUID | None] = mapped_column(ForeignKey("tenants.id"))
    reviewed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
