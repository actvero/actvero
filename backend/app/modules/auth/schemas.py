from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    email: str | None
    avatar_url: str | None = None


class EnterpriseAccess(BaseModel):
    tenant_id: UUID
    name: str
    role: str
    status: str
    needs_login: bool


class SessionView(BaseModel):
    authenticated: bool
    server_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_policy: Literal["strict", "persistent"] | None = None
    session_expires_at: datetime | None = None
    reauthenticate_at: datetime | None = None
    csrf: str
    user: UserView | None = None
    organization: EnterpriseAccess | None = None
    organizations: list[EnterpriseAccess] = Field(default_factory=list)
    setup_complete: bool
    setup_account_created: bool = False
    invitations_enabled: bool
    invitation_hours: int | None
    account_url: str | None = None
    platform_operator: bool = False
    platform_edition: str = "community"
    registration_mode: str = "invite"
    platform_name: str = "Actvero"
    platform_logo_url: str | None = None


class WorkspaceSelection(BaseModel):
    tenant_id: UUID | None = None


class SecretInput(BaseModel):
    token: str = Field(min_length=20, max_length=200)


class InvitationClaim(SecretInput):
    email: EmailStr | None = None
    name: str | None = Field(default=None, max_length=100)


class OrganizationInvitationClaim(BaseModel):
    token: str | None = Field(default=None, min_length=20, max_length=200)
    email: EmailStr | None = None
    name: str | None = Field(default=None, max_length=100)
    organization_name: str | None = Field(default=None, max_length=60)


class Message(BaseModel):
    message: str


class SetupRegistration(BaseModel):
    organization_name: str | None = Field(default=None, max_length=60)
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=128)


class SetupResult(BaseModel):
    tenant_id: UUID
    name: str


class InvitationPreview(BaseModel):
    state: str
    activation_required: bool = False
    tenant_name: str | None = None
    email: str | None = None
    role: str = "member"
    expires_at: datetime | None = None


class OrganizationInvitationPreview(BaseModel):
    state: str
    activation_required: bool = False
    organization_name: str | None = None
    email: str | None = None
    expires_at: datetime | None = None


class PasswordAction(BaseModel):
    url: str
