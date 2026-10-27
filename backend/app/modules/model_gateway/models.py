from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class GatewayDirectory(Base):
    """Read cache only; channel configuration remains owned by New API."""

    __tablename__ = "newapi_model_directories"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    channel_id: Mapped[int] = mapped_column(primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(64))
    models: Mapped[list[str]] = mapped_column(JSONB, default=list)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    channel_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
