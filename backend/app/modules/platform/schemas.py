from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator

from app.modules.auth.schemas import UserView


class OrganizationInvitationCreate(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=720)
    recipient_email: EmailStr | None = None


class OrganizationInvitation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    organization_id: UUID | None
    organization_name: str | None
    expires_at: datetime
    created_at: datetime
    can_copy: bool = False
    recipient_email: str | None = None


class OrganizationInvitationPage(BaseModel):
    items: list[OrganizationInvitation]
    total: int


class PlatformOrganization(BaseModel):
    id: UUID
    name: str
    active: bool
    member_count: int
    administrator_email: str | None
    administrator_status: str
    created_at: datetime


class PlatformOrganizationPage(BaseModel):
    items: list[PlatformOrganization]
    total: int


class OrganizationCreated(BaseModel):
    organization: PlatformOrganization | None = None
    invitation: OrganizationInvitation
    invite_url: str
    mail_status: str


class OrganizationInvitationLink(BaseModel):
    invite_url: str


class PortalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portal_enabled: bool = Field(strict=True)


class CliSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = Field(strict=True)


class CliSettingsView(BaseModel):
    enabled: bool
    source: Literal["environment", "platform"]
    server_url: str
    client_id: str
    issuer: str


class PlatformSettingsView(BaseModel):
    platform_name: str
    logo_url: str | None = None
    smtp_configured: bool
    smtp_host: str | None = None
    smtp_from: str | None = None


class PlatformSettingsUpdate(BaseModel):
    platform_name: str = Field(min_length=1, max_length=80)

    @field_validator("platform_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("平台名称不能为空或包含控制字符")
        return value.strip()


class MailSettingsView(BaseModel):
    enabled: bool
    source: Literal["environment", "platform"]
    host: str
    port: int
    security: Literal["starttls", "tls", "none"]
    username: str
    sender: str
    password_set: bool


class MailSettingsUpdate(BaseModel):
    enabled: bool = True
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    security: Literal["starttls", "tls", "none"] = "starttls"
    username: str = Field(default="", max_length=320)
    sender: EmailStr
    password: SecretStr | None = Field(default=None, max_length=1000)
    clear_password: bool = False

    @field_validator("host")
    @classmethod
    def valid_host(cls, value: str) -> str:
        value = value.strip()
        if not value or any(c.isspace() or c in "/\\:@?#" for c in value):
            raise ValueError("请输入 SMTP 主机名，不包含协议和端口")
        return value


class MailRecipient(BaseModel):
    email: EmailStr


class MailTemplateView(BaseModel):
    subject: str
    html: str


class RegistrationPolicy(BaseModel):
    mode: Literal["invite", "approval", "self_service"] = "invite"
    invitation_verify_email: bool = False


class RegistrationPolicyView(RegistrationPolicy):
    mail_enabled: bool


class OrganizationName(BaseModel):
    organization_name: str = Field(min_length=2, max_length=60)

    @field_validator("organization_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2 or any(ord(c) < 32 for c in value):
            raise ValueError("组织名称至少 2 个字符，不能包含控制字符")
        return value


class OrganizationCreate(OrganizationName):
    confirmed_user_id: UUID | None = None


class OpeningSubmit(OrganizationName):
    invitation: bool = False
    confirmed_user_id: UUID | None = None


class OpeningRegistration(BaseModel):
    invitation: bool = False
    # Optional only for compatibility with an already-open legacy registration form.
    organization_name: str = Field(default="", max_length=60)
    name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=128)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("请填写管理员姓名")
        return value.strip()


class OpeningFlowStart(BaseModel):
    invitation: bool = False
    token: str | None = Field(default=None, min_length=16, max_length=200)


class OpeningFlowView(BaseModel):
    flow_id: UUID


class OpeningDraft(BaseModel):
    organization_name: str = Field(default="", max_length=60)


class OpeningPreview(BaseModel):
    state: str
    account: UserView | None = None
    mode: str = "invite"
    organization_name: str = ""
    recipient_email: str | None = None
    verify_email: bool = False
    reason: str | None = None
    organization_id: UUID | None = None
    resume: bool = False


class OpeningApplication(BaseModel):
    id: UUID
    organization_name: str
    applicant_name: str
    applicant_email: str | None
    status: str
    reason: str | None
    created_at: datetime
    organization_id: UUID | None


class OpeningApplicationPage(BaseModel):
    items: list[OpeningApplication]
    total: int


class OpeningDecision(BaseModel):
    approve: bool
    reason: str = Field(default="", max_length=500)


class OrganizationUpdate(OrganizationName):
    active: bool
