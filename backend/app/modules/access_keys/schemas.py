from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class KeyGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["llm", "mcp"]
    resource_id: UUID
    actions: list[Literal["read", "invoke"]] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique(self) -> "KeyGrant":
        if len(set(self.actions)) != len(self.actions):
            raise ValueError("权限不可重复")
        return self


class KeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    creation_id: UUID
    name: str = Field(min_length=1, max_length=100)
    expires_at: AwareDatetime | None = None
    grants: list[KeyGrant] | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def unique(self) -> "KeyCreate":
        if self.grants is not None and len({(g.kind, g.resource_id) for g in self.grants}) != len(
            self.grants
        ):
            raise ValueError("资源不可重复")
        return self


class KeyGrantView(KeyGrant):
    name: str
    identifier: str


class KeyView(BaseModel):
    id: UUID
    member_id: UUID
    member_name: str
    name: str
    hint: str
    can_reveal: bool = False
    managed_disabled: bool
    scope_mode: Literal["member", "selected"]
    grants: list[KeyGrantView]
    status: Literal["active", "disabled", "revoked", "expired", "blocked"]
    version: int
    created_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None


class KeyPage(BaseModel):
    items: list[KeyView]
    total: int
    page: int


class KeyCreated(BaseModel):
    key: KeyView
    secret: str
    llm_base_url: str


class KeyAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    action: Literal["disable", "enable", "revoke", "delete"]


class KeyPolicyView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)
    enabled: bool
    max_days: int | None = Field(default=None, ge=1, le=3650)


class KeyResource(BaseModel):
    kind: Literal["llm", "mcp"]
    id: UUID
    name: str
    identifier: str
    endpoint: str


class KeyResourcePage(BaseModel):
    items: list[KeyResource]
    total: int
    page: int


class KeyUsage(BaseModel):
    id: UUID
    kind: str
    resource_name: str
    operation: str
    status: str
    duration_ms: int | None
    created_at: datetime


class KeyUsagePage(BaseModel):
    items: list[KeyUsage]
    total: int
    page: int


class KeyReveal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class KeySecret(BaseModel):
    secret: str
