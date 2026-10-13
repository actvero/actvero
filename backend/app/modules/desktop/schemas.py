import re
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.modules.auth.schemas import UserView


class DesktopInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartLogin(DesktopInput):
    contract_version: Literal[1] = Field(description="当前桌面登录契约固定为 1。")
    redirect_uri: str = Field(
        max_length=200,
        description="主进程已监听的回调：http://127.0.0.1:<1024"
        "..65535>/actvero/callback；不允许其他主"
        "机、路径或查询参数。",
    )
    code_challenge: str = Field(
        pattern=r"^[A-Za-z0-9_-]{43}$",
        description="原 verifier 的 SHA-256 摘要，经无填充 base64url 编码；只支持 S256。",
    )
    device_name: str = Field(
        min_length=1, max_length=100, description="用于设备列表展示，不作为设备认证依据。"
    )
    os: Literal["macOS", "Windows", "Linux"] = Field(description="桌面操作系统。")
    app_version: str = Field(
        min_length=1, max_length=50, description="桌面应用版本，用于定位兼容问题。"
    )
    reauthenticate: bool = Field(
        default=False, description="true 强制重新认证；false 可复用仍有效的上游 SSO。"
    )

    @field_validator("redirect_uri")
    @classmethod
    def loopback(cls, value: str) -> str:
        p = urlsplit(value)
        if (
            p.scheme != "http"
            or p.hostname != "127.0.0.1"
            or not p.port
            or not 1024 <= p.port <= 65535
            or p.path != "/actvero/callback"
            or p.query
            or p.fragment
            or p.username
            or p.password
            or value != f"http://127.0.0.1:{p.port}/actvero/callback"
        ):
            raise ValueError("仅支持已登记的本机回调")
        return value

    @field_validator("device_name", "app_version")
    @classmethod
    def display_text(cls, value: str) -> str:
        value = value.strip()
        if not value or re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("显示信息无效")
        return value


class LoginAttempt(BaseModel):
    attempt_id: UUID = Field(description="本次登录尝试 ID，后续兑换和取消使用。")
    authorization_url: str = Field(
        description="主进程在系统浏览器打开的授权地址；不得记录完整 URL。"
    )
    state: str = Field(description="保存并与浏览器回调精确比较，不能使用其他尝试的 state。")
    issuer: str = Field(description="期望的身份服务 issuer，必须与回调 iss 一致。")
    expires_at: datetime = Field(description="登录尝试到期时间。")


class LoginProof(DesktopInput):
    attempt_id: UUID = Field(description="login/start 返回的尝试 ID。")
    state: SecretStr = Field(min_length=43, max_length=100, description="原登录尝试的随机 state。")
    code_verifier: SecretStr = Field(
        min_length=43,
        max_length=128,
        description="主进程生成并保管的原 PKCE verifier；不传给渲染进程。",
    )

    @field_validator("code_verifier")
    @classmethod
    def verifier(cls, value: SecretStr) -> SecretStr:
        if not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", value.get_secret_value()):
            raise ValueError("PKCE verifier 格式无效")
        return value


class ExchangeLogin(LoginProof):
    code: SecretStr = Field(
        min_length=1, max_length=4096, description="浏览器回调的一次性授权码，不是访问令牌。"
    )
    issuer: str = Field(
        max_length=500, description="回调 iss；必须与原尝试及 metadata issuer 精确一致。"
    )


class RefreshSession(DesktopInput):
    recovery_version: Literal[1, 2] = Field(
        default=1,
        description=("2：先持久化原refresh与request_id，落盘新凭据后明确确认；1：保持短重试窗口。"),
    )
    refresh_token: SecretStr = Field(
        min_length=20,
        max_length=200,
        description="当前设备续期凭据；仅主进程安全存储，不记录或透传给上游。",
    )
    request_id: UUID = Field(
        description="本轮续期 UUID；发送前持久化，网络重试复用同一值。不是响应中的链路 request_id。"
    )


class RefreshAcknowledgement(DesktopInput):
    refresh_token: SecretStr = Field(min_length=20, max_length=200)
    request_id: UUID


class DesktopWorkspace(DesktopInput):
    tenant_id: UUID


class LogoutSession(DesktopInput):
    refresh_token: SecretStr = Field(
        min_length=20,
        max_length=200,
        description="所属设备的续期凭据；仅退出时可使用已轮换或过期版本。",
    )


class DesktopTokens(BaseModel):
    access_token: str = Field(
        description="短期不透明访问凭据，以 Authorization: Bearer 发送；客户端不要解析。"
    )
    refresh_token: str = Field(description="轮换续期凭据，主进程安全存储；成功后原子替换旧值。")
    token_type: Literal["Bearer"] = Field(
        default="Bearer", description="Authorization 使用的认证方案。"
    )
    scope: Literal["desktop:self"] = Field(
        default="desktop:self",
        description="当前只包含桌面本人账号/设备范围，不授予 MCP 或管理员权限。",
    )
    device_session_id: UUID = Field(description="本次独立设备会话 ID。")
    expires_in: int = Field(description="访问凭据剩余有效时长，单位秒。")
    server_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_policy: Literal["strict", "persistent"] = "strict"
    reauthenticate_at: datetime | None = None
    acknowledgement_required: bool = False
    refresh_request_id: UUID | None = None
    recovery_until: datetime | None = None
    session_expires_at: datetime = Field(
        description="当前设备恢复截止；strict固定，persistent在成功续期后滚动。"
    )
    idle_expires_at: datetime = Field(description="当前非活跃截止；persistent按成功refresh计时。")


class DeviceView(BaseModel):
    id: UUID
    name: str
    os: str
    app_version: str
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime
    status: Literal["active", "expired", "revoked"]
    current: bool = False


class DeviceList(BaseModel):
    items: list[DeviceView]


class DesktopOrganization(BaseModel):
    tenant_id: UUID = Field(description="当前组织 ID，bootstrap 使用此值。")
    membership_id: UUID = Field(description="当前组织内成员 ID，不是 user_id。")
    name: str
    role: Literal["administrator", "member"]
    status: Literal["active", "paused", "removed", "unavailable"] = Field(
        description="当前成员/组织状态；只有有效资格才能使用组织资源。"
    )
    needs_login: bool = Field(description="成员访问曾被暂停等情况下是否需要重新认证。")


class DesktopMe(BaseModel):
    user: UserView = Field(description="平台本人资料，与 Web 共用内部用户身份。")
    organization: DesktopOrganization | None = Field(
        description="唯一组织及成员状态；未加入时为 null。"
    )
    device: DeviceView = Field(description="当前设备会话的公开信息。")
    organizations: list[DesktopOrganization] = Field(default_factory=list)
    organization_state: Literal[
        "ready", "selection_required", "no_available_organization", "blocked"
    ] = "no_available_organization"
    session_policy: Literal["strict", "persistent"] = "strict"
    recovery_expires_at: datetime | None = None
    reauthenticate_at: datetime | None = None
    server_time: datetime = Field(default_factory=lambda: datetime.now(UTC))
    account_url: str = Field(description="系统浏览器打开的账号管理地址，仍需独立 Web 会话。")


class ModuleState(BaseModel):
    name: Literal["models", "mcp", "skills", "experts"] = Field(description="桌面能力模块。")
    status: Literal["available", "not_implemented"] = Field(
        default="not_implemented",
        description="available 表示平台接口可用；not_implemented 表示未实现。",
    )
    reason: Literal["module_not_implemented"] | None = Field(
        default="module_not_implemented", description="未开放原因；已实现为 null。"
    )


class DesktopBootstrap(DesktopMe):
    contract_version: Literal[1] = 1
    modules: list[ModuleState]


class DesktopBranding(BaseModel):
    name: str
    logo_url: str | None = None
    revision: UUID
    assets: dict[str, str] = Field(default_factory=dict)
    favicon_url: str | None = None
    apple_icon_url: str | None = None


class DesktopCapabilities(BaseModel):
    service_branding: Literal[1] = 1
    device_session_policy: Literal[1] = 1
    refresh_recovery: Literal[2] = 2
    organization_selection: Literal[1] = 1
    historical_resource_binding: Literal[1] = 1
    dependency_contract: Literal[3] = 3
    mcp_reference_revisions: Literal[1] = 1
    selective_dependency_update: Literal[1] = 1
    mcp_connection_recovery: Literal[1] = 1
    same_origin_identity: Literal[1] | None = None


class DesktopMetadata(BaseModel):
    instance_id: UUID
    branding: DesktopBranding
    capabilities: DesktopCapabilities
    contract_version: Literal[1] = 1
    issuer: str
    discovery_url: str
    client_id: str
    api_base: str
    callback_template: str = "http://127.0.0.1:{port}/actvero/callback"
    callback_port_min: int = 1024
    callback_port_max: int = 65535
    exchange_path: str = "/desktop/login/exchange"
    refresh_path: str = "/desktop/refresh"
    logout_path: str = "/desktop/logout"
    access_seconds: int
    session_hours: int
    idle_minutes: int
    retry_seconds: int
    session_policy: Literal["strict", "persistent"] = "strict"
    recovery_days: int = 30
    reauthentication_days: int | None = None
    expert_access_versions: list[int] = Field(default_factory=lambda: [1, 2, 3])
    refresh_recovery_versions: list[int] = Field(default_factory=lambda: [1, 2])
    unconfirmed_days: int = 7
    refresh_acknowledgement_path: str = "/desktop/refresh/acknowledge"
    organization_selection_path: str = "/desktop/organization"


class DesktopErrorDetail(BaseModel):
    code: str = Field(description="供客户端分支处理的稳定错误码。")
    message: str = Field(description="供用户阅读的错误提示，不应当作程序判断条件。")
    request_id: str = Field(description="平台请求跟踪编号，可用于查日志；不是续期幂等 UUID。")


class DesktopErrorResponse(BaseModel):
    error: DesktopErrorDetail
