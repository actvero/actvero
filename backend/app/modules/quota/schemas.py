from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

Points = Annotated[
    str, StringConstraints(pattern=r"^(0|[1-9][0-9]{0,17})(\.[0-9]{1,12})?$", max_length=31)
]


class FixedHours(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["fixed_hours"]
    hours: int = Field(ge=1, le=720, strict=True)
    points: Points


class CalendarWeek(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["calendar_week"]
    points: Points
    timezone: str = Field(min_length=1, max_length=100)
    week_start: int = Field(ge=0, le=6, strict=True)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("请选择有效的 IANA 时区") from exc
        return value


QuotaRule = Annotated[FixedHours | CalendarWeek, Field(discriminator="kind")]


class QuotaPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    priority: int = Field(ge=0, le=1000000, strict=True)
    member_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    rules: list[QuotaRule] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if len(set(self.member_ids)) != len(self.member_ids):
            raise ValueError("成员不能重复")
        if (self.priority == 0 and self.member_ids) or (self.priority > 0 and not self.member_ids):
            raise ValueError("默认策略适用全部成员；其他策略至少选择一名成员")
        keys = [(r.kind, r.hours if isinstance(r, FixedHours) else None) for r in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("同一周期只能配置一条额度规则")
        return self


class QuotaPolicyUpdate(QuotaPolicyInput):
    version: int = Field(ge=1)


class QuotaPolicyView(QuotaPolicyInput):
    id: UUID
    archived: bool
    version: int
    created_at: datetime
    updated_at: datetime


class QuotaPolicyPage(BaseModel):
    items: list[QuotaPolicyView]
    total: int
    has_default: bool
    default_timezone: str | None = None
    enforcement: Literal["active"] = "active"


class QuotaArchive(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    archived: bool


class PolicyMatch(BaseModel):
    id: UUID
    name: str
    priority: int


class MemberQuotaMatch(BaseModel):
    member_id: UUID
    name: str
    email: str | None
    role: str
    matched: list[PolicyMatch]
    selected: PolicyMatch | None
    rules: list[QuotaRule]


class QuotaMatchPage(BaseModel):
    items: list[MemberQuotaMatch]
    total: int
    enforcement: Literal["active"] = "active"
