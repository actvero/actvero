from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, StringConstraints


class MemberView(BaseModel):
    id: UUID
    name: str
    email: str | None
    role: str
    status: str
    source: str
    version: int
    joined_at: datetime
    is_self: bool


class MemberPage(BaseModel):
    items: list[MemberView]
    total: int
    page: int
    page_size: int = 20


class MemberChange(BaseModel):
    action: Literal["role", "pause", "restore", "remove"]
    role: Literal["administrator", "member"] | None = None
    version: int = Field(ge=1)
    reason: str = Field(default="", max_length=500)


class InviteInput(BaseModel):
    request_id: UUID
    email: EmailStr
    name: str = Field(default="", max_length=200)


class InvitationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    email: str
    name: str
    status: str
    mail_status: str
    expires_at: datetime
    created_at: datetime
    last_sent_at: datetime | None


class InvitationPage(BaseModel):
    items: list[InvitationView]
    total: int
    page: int
    page_size: int = 20


class DeliveryInput(BaseModel):
    request_id: UUID
    replace: bool = False


class MemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    email: EmailStr
    role: Literal["administrator", "member"] = "member"
    password: SecretStr = Field(min_length=12, max_length=128)


class MemberCreated(BaseModel):
    member: MemberView
    initial_password_reused: bool = False


class MemberSelectionQuery(BaseModel):
    member_ids: list[UUID] = Field(max_length=1000)
    q: str = Field(default="", max_length=200)
    page: int = Field(default=1, ge=1)
