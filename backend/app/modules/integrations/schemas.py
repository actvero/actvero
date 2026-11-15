from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class IntegrationCapabilities(BaseModel):
    models_enabled: bool = False
    mcp_enabled: bool = False
    skills_enabled: bool = False
    experts_enabled: bool = False
    knowledge_enabled: bool = False


class ApplicationCreate(IntegrationCapabilities):
    model_config = ConfigDict(extra="forbid")

    name: Name


class ApplicationUpdate(ApplicationCreate):
    models_enabled: bool
    enabled: bool
    version: int = Field(ge=1)


class ApplicationView(ApplicationUpdate):
    mcp_enabled: bool
    skills_enabled: bool
    experts_enabled: bool
    knowledge_enabled: bool
    id: UUID
    created_at: datetime
    last_used_at: datetime | None
    model_base_url: str
    integration_base_url: str


class ApplicationPage(BaseModel):
    items: list[ApplicationView]
    total: int


class ApplicationKeyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    days: Literal[30, 90, 365] = 90


class ApplicationKeyView(BaseModel):
    id: UUID
    name: str
    hint: str
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime | None
    status: Literal["active", "expired", "revoked"]


class ApplicationKeyCreated(BaseModel):
    key: ApplicationKeyView
    secret: str


class ApplicationConnection(IntegrationCapabilities):
    application_id: UUID
    name: str
    model_base_url: str
    integration_base_url: str


class ApplicationCallStatus(BaseModel):
    id: UUID
    status: str
    settlement_status: str
