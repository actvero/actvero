from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.service import now
from app.modules.object_storage.models import ObjectStorage as ClientStorage  # noqa: F401


class ClientDistribution(Base):
    __tablename__ = "client_distributions"
    release_id: Mapped[UUID] = mapped_column(ForeignKey("client_releases.id"), primary_key=True)
    source_commit: Mapped[str | None] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(20))
    updates_enabled: Mapped[bool] = mapped_column(default=True)
    minimum_os: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)


class ClientArtifact(Base):
    __tablename__ = "client_artifacts"
    __table_args__ = (UniqueConstraint("release_id", "target", "role"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("client_releases.id"), index=True)
    target: Mapped[str] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(20))
    filename: Mapped[str] = mapped_column(String(180))
    source: Mapped[str] = mapped_column(String(20))
    url: Mapped[str | None] = mapped_column(String(2048))
    storage_id: Mapped[UUID | None] = mapped_column(ForeignKey("client_storage.id"))
    object_key: Mapped[str | None] = mapped_column(String(500))
    source_url_ciphertext: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    expected_sha512: Mapped[str | None] = mapped_column(String(88))
    sha512: Mapped[str | None] = mapped_column(String(88))
    sha256: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    range_supported: Mapped[bool] = mapped_column(default=False)
    validation: Mapped[dict[str, object]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClientUpload(Base):
    __tablename__ = "client_uploads"
    id: Mapped[UUID] = mapped_column(primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("client_artifacts.id"), unique=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    upload_id: Mapped[str | None] = mapped_column(Text)
    part_size: Mapped[int] = mapped_column(default=16 * 1024 * 1024)
    parts: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="starting")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClientJob(Base):
    __tablename__ = "client_distribution_jobs"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    artifact_id: Mapped[UUID] = mapped_column(ForeignKey("client_artifacts.id"), index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    processed_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ClientUpdateHead(Base):
    __tablename__ = "client_update_heads"
    channel: Mapped[str] = mapped_column(String(20), primary_key=True)
    target: Mapped[str] = mapped_column(String(30), primary_key=True)
    release_id: Mapped[UUID | None] = mapped_column(ForeignKey("client_releases.id"))
    revision: Mapped[int] = mapped_column(default=1)
    manifest: Mapped[str] = mapped_column(Text)


class ClientPublicationPlan(Base):
    __tablename__ = "client_publication_plans"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    release_id: Mapped[UUID] = mapped_column(ForeignKey("client_releases.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    release_revision: Mapped[int]
    heads: Mapped[dict[str, int]] = mapped_column(JSON)
    artifact_ids: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(default=False)


__all__ = ["ClientStorage"]
