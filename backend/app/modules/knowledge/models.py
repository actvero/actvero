from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.service import now


class KnowledgeSettings(Base):
    __tablename__ = "knowledge_settings"
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    embedding_model_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_models.id"))
    rerank_model_id: Mapped[UUID | None] = mapped_column(ForeignKey("llm_models.id"))
    rerank_enabled: Mapped[bool] = mapped_column(default=False)
    executor_member_id: Mapped[UUID | None] = mapped_column(ForeignKey("memberships.id"))
    authorized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ParserCredential(Base):
    __tablename__ = "knowledge_parser_credentials"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    account: Mapped[str] = mapped_column(String(100))
    secret: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(default=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(String(300), default="")


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    archived: Mapped[bool] = mapped_column(default=False)
    description: Mapped[str] = mapped_column(String(1000), default="")
    audience: Mapped[str] = mapped_column(String(20), default="administrators")
    member_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    department_grants: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    chunking: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    embedding_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("base_id", "upload_id"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    base_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    upload_id: Mapped[UUID]
    filename: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    active_generation_id: Mapped[UUID | None]
    latest_generation_id: Mapped[UUID | None]
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KnowledgeGeneration(Base):
    __tablename__ = "knowledge_generations"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_documents.id"), index=True)
    actor_member_id: Mapped[UUID] = mapped_column(ForeignKey("memberships.id"))
    chunking: Mapped[dict[str, Any]] = mapped_column(JSONB)
    embedding_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    error: Mapped[str] = mapped_column(String(500), default="")
    raw_parse: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, deferred=True)
    blocks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, deferred=True)
    batch_id: Mapped[str | None] = mapped_column(String(100))
    credential_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_parser_credentials.id")
    )
    upload_url: Mapped[str | None] = mapped_column(Text)
    submission_pending: Mapped[bool] = mapped_column(default=False)
    inference_pending: Mapped[bool] = mapped_column(default=False)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (UniqueConstraint("generation_id", "sequence"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    generation_id: Mapped[UUID] = mapped_column(ForeignKey("knowledge_generations.id"), index=True)
    sequence: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    vector: Mapped[list[float] | None] = mapped_column(JSONB(none_as_null=True), deferred=True)
