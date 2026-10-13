"""Explicit, bounded version selections shared with Skill publication."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExactSkillChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=80)
    from_version_id: UUID
    from_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    to_version_id: UUID
    to_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExpertDraftSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expert_id: UUID
    revision: int = Field(ge=1)
    changes: list[ExactSkillChange] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique(self) -> "ExpertDraftSelection":
        if len({c.key for c in self.changes}) != len(self.changes):
            raise ValueError("不能重复选择依赖")
        return self


class ExpertSkillRefresh(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    request_id: UUID | None = None
    changes: list[ExactSkillChange] | None = Field(default=None, min_length=1, max_length=32)

    @model_validator(mode="after")
    def explicit_command(self) -> "ExpertSkillRefresh":
        if self.changes is not None:
            if self.request_id is None:
                raise ValueError("选择性更新必须提供请求编号")
            if len({c.key for c in self.changes}) != len(self.changes):
                raise ValueError("不能重复选择依赖")
        elif self.request_id is not None:
            raise ValueError("提供请求编号时必须显式选择更新项")
        return self


class DependencyCommandView(BaseModel):
    request_id: UUID
    action: str
    resource_id: UUID
    completed_at: datetime
    updated_experts: list[dict[str, str | int]]
