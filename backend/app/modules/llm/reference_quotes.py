"""Bounded reference provenance, kept separate from executable tariffs."""

import json
import math
from datetime import datetime
from urllib.parse import urlsplit

from pydantic import Field, JsonValue, field_validator

from app.modules.llm.schemas import Input


class QuoteSnapshot(Input):
    provider: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=300)
    fetched_at: datetime
    source_updated_at: str | None = Field(default=None, max_length=100)
    currency: str = Field(default="USD", min_length=1, max_length=32)
    unit: int = Field(default=1000000, ge=1, le=1000000000000, strict=True)
    metric: str = Field(default="tokens", min_length=1, max_length=100)
    source_url: str | None = Field(default=None, max_length=2048)
    raw_cost: dict[str, JsonValue] = Field(default_factory=dict)
    conditions: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("fetched_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("报价抓取时间必须包含时区")
        return value

    @field_validator("source_url")
    @classmethod
    def safe_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
            ):
                raise ValueError("报价来源只接受无凭据的 HTTPS 地址")
        except ValueError as exc:
            raise ValueError("报价来源地址无效") from exc
        return value

    @field_validator("conditions")
    @classmethod
    def bounded_conditions(cls, value: list[str]) -> list[str]:
        if any(len(item) > 1000 for item in value):
            raise ValueError("单条报价条件不能超过 1000 字符")
        return value

    @field_validator("raw_cost")
    @classmethod
    def bounded_cost(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        def validate(item: JsonValue, depth: int = 0) -> None:
            if depth > 8:
                raise ValueError("报价结构层级过深")
            if isinstance(item, dict):
                if len(item) > 64 or any(len(key) > 200 for key in item):
                    raise ValueError("报价字段数量或名称超限")
                for child in item.values():
                    validate(child, depth + 1)
            elif isinstance(item, list):
                if len(item) > 256:
                    raise ValueError("报价数组超限")
                for child in item:
                    validate(child, depth + 1)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("报价数值必须有限")

        validate(value)
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode()) > 32768:
            raise ValueError("报价快照不能超过 32 KiB")
        return value
