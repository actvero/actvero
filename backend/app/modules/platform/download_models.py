from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientRelease(Base):
    __tablename__ = "client_releases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'withdrawn')", name="client_release_status"
        ),
        CheckConstraint("revision > 0", name="client_release_revision"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(50), unique=True)
    release_date: Mapped[date] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, default="")
    assets: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    revision: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientRecommendation(Base):
    __tablename__ = "client_recommendations"
    __table_args__ = (
        CheckConstraint("platform IN ('windows', 'macos')", name="client_recommendation_platform"),
        CheckConstraint(
            "architecture IN ('x64', 'arm64', 'universal')",
            name="client_recommendation_architecture",
        ),
        CheckConstraint(
            "platform != 'windows' OR architecture != 'universal'",
            name="client_recommendation_target",
        ),
    )
    platform: Mapped[str] = mapped_column(String(20), primary_key=True)
    architecture: Mapped[str] = mapped_column(String(20), primary_key=True)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("client_releases.id"))


class ClientReleaseEvent(Base):
    """Deployment audit, deliberately independent from tenant AuditEvent."""

    __tablename__ = "client_release_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    actor_name: Mapped[str] = mapped_column(String(200))
    release_id: Mapped[UUID] = mapped_column(index=True)
    version: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
