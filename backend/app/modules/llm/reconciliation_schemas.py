"""Strict, metric-tagged administrative settlement reconciliation contracts."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Metric = Literal["tokens", "characters", "search_units", "images", "seconds"]
Count = int


class TaggedUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    metric: Metric
    input_tokens: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    output_tokens: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    cache_read_tokens: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    cache_write_5m_tokens: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    cache_write_1h_tokens: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    input_characters: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    search_units: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    audio_duration_ms: Count | None = Field(default=None, ge=0, le=120000, strict=True)
    image_count: Count | None = Field(default=None, ge=0, le=10**12, strict=True)


class LegacyReconcileUsage(BaseModel):
    """Old field names with explicit-presence tracking and strict quantities."""

    model_config = ConfigDict(extra="forbid", strict=True)

    input: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    output: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    cache_read: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    cache_write_5m: Count | None = Field(default=None, ge=0, le=10**12, strict=True)
    cache_write_1h: Count | None = Field(default=None, ge=0, le=10**12, strict=True)


class ReconcileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: int = Field(ge=1, strict=True)
    request_id: UUID | None = None
    action: Literal["settle", "release"]
    usage: TaggedUsage | LegacyReconcileUsage | None = None
    reason: str = Field(min_length=1, max_length=500)


class ReconciliationPreview(BaseModel):
    call_id: UUID
    version: int
    action: Literal["settle", "release"]
    metric: Metric
    usage: dict[str, int]
    amount: str
    points: str
    currency: str
