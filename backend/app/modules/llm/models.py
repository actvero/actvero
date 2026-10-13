from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.service import now


class ModelChannel(Base):
    __tablename__ = "model_channels"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(Text, default="")
    base_url: Mapped[str] = mapped_column(String(2000))
    # Empty snapshots from older callers retain the legacy base_url semantics.
    connection: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    manual_enabled: Mapped[bool] = mapped_column(default=True)
    automatic_protection: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: {"enabled": True}
    )
    test_defaults: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Independent of cosmetic edits; NULL supports legacy in-memory fixtures.
    routing_version: Mapped[int | None] = mapped_column()
    # Retained historical JSON for upgrade fidelity; runtime uses explicit bindings.
    routing: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    auth_mode: Mapped[str] = mapped_column(String(20))
    sealed_key: Mapped[str | None] = mapped_column(Text)
    timeout_seconds: Mapped[int] = mapped_column(default=20)
    declared_apis: Mapped[list[str]] = mapped_column(JSONB, default=list)
    archived: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)
    # Registration is a channel inventory, never a published platform model.
    models: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    snapshot: Mapped[list[str]] = mapped_column(JSONB, default=list)
    snapshot_id: Mapped[UUID | None] = mapped_column()
    snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CatalogModel(Base):
    __tablename__ = "llm_models"
    __table_args__ = (UniqueConstraint("tenant_id", "slug"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    slug: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(100))
    # Typed model configuration, prices and explicit runtime access policy.
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB)
    archived: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class MutationReceipt(Base):
    """Actor-scoped management idempotency; never stores a secret or form body."""

    __tablename__ = "llm_mutation_receipts"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    scope: Mapped[str] = mapped_column(String(60), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    payload_digest: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[UUID] = mapped_column()
    state: Mapped[str] = mapped_column(String(20), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelImportReceipt(Base):
    __tablename__ = "llm_model_import_receipts"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    request_id: Mapped[UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ModelCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        CheckConstraint(
            "(source = 'channel_diagnostic' AND model_id IS NULL) OR "
            "(source <> 'channel_diagnostic' AND model_id IS NOT NULL)",
            name="ck_llm_call_model_source",
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    model_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_models.id"), index=True)
    channel_id: Mapped[UUID] = mapped_column(ForeignKey("model_channels.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    device_id: Mapped[UUID | None] = mapped_column(ForeignKey("device_sessions.id"))
    access_key_id: Mapped[UUID | None] = mapped_column(ForeignKey("access_keys.id"), index=True)
    source: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(60))
    duration_ms: Mapped[int | None] = mapped_column()
    termination_code: Mapped[str | None] = mapped_column(String(60))
    attempts: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # No input, documents, vectors, credentials or upstream error bodies.
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    prices: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    estimates: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class RouteHealth(Base):
    __tablename__ = "llm_route_health"
    __table_args__ = (
        CheckConstraint(
            "block_reason IS NULL OR block_reason IN "
            "('model_unavailable', 'unclassified_rejection')",
            name="ck_llm_route_block_reason",
        ),
        CheckConstraint("health_generation >= 0", name="ck_llm_route_generation"),
    )
    # Hash of tenant + model + binding; channel credential health uses its own key.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failures: Mapped[int] = mapped_column(default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    probe_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked: Mapped[bool] = mapped_column(default=False)
    block_reason: Mapped[str | None] = mapped_column(String(32))
    health_generation: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class PointConversion(Base):
    """Immutable revisions; changing the ratio never rewrites historical calculations."""

    __tablename__ = "llm_point_conversions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version"),
        CheckConstraint("points_per_currency > 0 AND points_per_currency <= 1000000000000"),
        CheckConstraint("version >= 1"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    points_per_currency: Mapped[Decimal] = mapped_column(Numeric(25, 12))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class UsageSettlement(Base):
    """One monetary reservation/settlement per logical request; points are derived."""

    __tablename__ = "llm_settlements"
    __table_args__ = (
        UniqueConstraint("tenant_id", "member_id", "idempotency_key"),
        CheckConstraint("reserved_amount >= 0 AND (amount IS NULL OR amount >= 0)"),
        CheckConstraint("status IN ('reserved', 'review', 'settled', 'released')"),
    )
    id: Mapped[UUID] = mapped_column(ForeignKey("llm_calls.id"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_fingerprint: Mapped[str | None] = mapped_column(String(67))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    currency: Mapped[str] = mapped_column(String(3))
    conversion_id: Mapped[UUID] = mapped_column(ForeignKey("llm_point_conversions.id"))
    ratio: Mapped[Decimal] = mapped_column(Numeric(25, 12))
    reserved_amount: Mapped[Decimal] = mapped_column(Numeric(60, 30))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(60, 30))
    price: Mapped[dict[str, Any]] = mapped_column(JSONB)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="reserved")
    version: Mapped[int] = mapped_column(default=1)
    reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuotaClock(Base):
    __tablename__ = "llm_quota_clocks"
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    windows: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
