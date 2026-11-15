from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.service import now


class IntegrationApplication(Base):
    __tablename__ = "integration_applications"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(default=True)
    mcp_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    skills_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    experts_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    knowledge_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    models_enabled: Mapped[bool] = mapped_column(default=False, server_default="false")
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IntegrationKey(Base):
    __tablename__ = "integration_keys"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("integration_applications.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hint: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
