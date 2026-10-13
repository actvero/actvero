from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.service import now


class AccessKey(Base):
    __tablename__ = "access_keys"
    __table_args__ = (UniqueConstraint("member_id", "creation_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"), index=True)
    identity_id: Mapped[UUID] = mapped_column(ForeignKey("login_identities.id"))
    creation_id: Mapped[UUID]
    sealed_secret: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hint: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100))
    scope_mode: Mapped[str] = mapped_column(
        String(16), default="selected", server_default="selected"
    )
    grants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    disabled: Mapped[bool] = mapped_column(default=False)
    managed_disabled: Mapped[bool] = mapped_column(default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    authenticated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AccessKeyPolicy(Base):
    __tablename__ = "access_key_policies"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    max_days: Mapped[int | None]
    version: Mapped[int] = mapped_column(default=1)
