from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
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


QuotaRule = FixedHours


class QuotaPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    is_default: bool = Field(default=False, strict=True)
    mode: Literal["limited", "unlimited"] = "limited"
    rules: list[QuotaRule] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.mode == "limited" and not self.rules:
            raise ValueError("周期限额至少配置一条规则")
        if self.mode == "unlimited" and self.rules:
            raise ValueError("不限额度不能同时配置周期上限")
        keys = [r.hours for r in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("同一周期只能配置一条额度规则")
        return self


class QuotaPolicyUpdate(QuotaPolicyInput):
    version: int = Field(ge=1)


class QuotaPolicyView(QuotaPolicyInput):
    is_default: bool = Field(...)
    mode: Literal["limited", "unlimited"] = Field(...)
    rules: list[QuotaRule] = Field(...)
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
    mode: Literal["limited", "unlimited"]
    is_default: bool


class QuotaAssignmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy_id: UUID | None
    version: int = Field(ge=0, strict=True)


class MemberQuotaMatch(BaseModel):
    member_id: UUID
    name: str
    email: str | None
    role: str
    status: Literal["active", "paused"]
    avatar_url: str | None = None
    assigned: PolicyMatch | None
    assignment_version: int
    selected: PolicyMatch | None
    rules: list[QuotaRule]


class QuotaMatchPage(BaseModel):
    items: list[MemberQuotaMatch]
    total: int
    enforcement: Literal["active"] = "active"
