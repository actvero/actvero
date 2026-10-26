from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # Community deployments stay single-organization. SaaS control-plane
    # work is enabled explicitly per deployment after operator bootstrap.
    platform_edition: Literal["community", "saas"] = "community"
    llm_allowed_private_origins: list[str] = []
    llm_public_dns: Literal["system", "cloudflare"] = "system"
    llm_outbox_dir: Path = PROJECT_ROOT / ".local" / "llm-outbox"
    llm_router_redis_url: SecretStr | None = None
    mcp_allowed_private_origins: list[str] = []
    mcp_public_dns: Literal["system", "cloudflare"] = "system"
    client_distribution_allowed_private_origins: list[str] = []
    client_distribution_worker_enabled: bool = True

    model_config = SettingsConfigDict(
        env_prefix="ACTVERO_", env_file=PROJECT_ROOT / ".env", extra="ignore", env_ignore_empty=True
    )

    database_url: SecretStr | None = None
    static_dir: Path = PROJECT_ROOT / "frontend" / "dist"
    oidc_issuer: str = "http://127.0.0.1:5196/realms/actvero"
    app_url: str = "http://127.0.0.1:5194"
    oidc_internal_url: str | None = None
    web_client_id: str = "actvero-web"
    web_client_secret: SecretStr | None = None
    session_encryption_key: SecretStr | None = None
    session_hours: int = Field(default=8, ge=1, le=24)
    # Opt in per deployment; legacy sessions retain their original strict deadline.
    web_session_policy: Literal["strict", "persistent"] = "strict"
    web_recovery_days: int = Field(default=30, ge=1, le=365)
    web_reauthentication_days: int | None = Field(default=90, ge=1, le=730)
    session_cookie_name: str = Field(
        default="actvero_community_session", pattern=r"^[A-Za-z0-9_-]{1,100}$"
    )
    provisioner_client_id: str = "actvero-provisioner"
    provisioner_client_secret: SecretStr | None = None
    desktop_client_id: str = "actvero-desktop"
    desktop_access_seconds: int = Field(default=300, ge=60, le=900)
    desktop_session_policy: Literal["strict", "persistent"] = "strict"
    desktop_recovery_days: int = Field(default=30, ge=1, le=365)
    desktop_reauthentication_days: int | None = Field(default=None, ge=1, le=730)
    desktop_unconfirmed_days: int = Field(default=7, ge=1, le=30)
    desktop_session_hours: int = Field(default=8, ge=1, le=24)
    desktop_idle_minutes: int = Field(default=60, ge=10, le=1440)
    desktop_login_seconds: int = Field(default=300, ge=60, le=600)
    desktop_retry_seconds: int = Field(default=120, ge=30, le=300)
    management_enabled: bool = False
    management_client_id: str = "actvero-cli"
    management_access_seconds: int = Field(default=300, ge=60, le=900)
    management_recovery_days: int = Field(default=30, ge=1, le=365)
    management_reauthentication_days: int = Field(default=90, ge=1, le=730)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    # Local Docker identity service may reach a host-loopback SMTP transport by its service DNS.
    identity_smtp_loopback_host: str | None = None
    identity_smtp_loopback_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_display_name: str = "Actvero"
    smtp_logo_url: str | None = None
    smtp_logo_is_wordmark: bool = False
    invitation_hours: int | None = Field(default=None, ge=1, le=720)

    @property
    def cookie_secure(self) -> bool:
        return self.app_url.startswith("https://")

    @property
    def identity_mail_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.provisioner_client_secret)

    @property
    def invitations_enabled(self) -> bool:
        return self.identity_mail_enabled and bool(self.invitation_hours)

    @model_validator(mode="after")
    def validate_origins(self) -> "Settings":
        if (
            self.web_reauthentication_days is not None
            and self.web_reauthentication_days < self.web_recovery_days
        ):
            raise ValueError("Web reauthentication cap must cover the recovery window")
        if (
            self.desktop_reauthentication_days is not None
            and self.desktop_reauthentication_days < self.desktop_recovery_days
        ):
            raise ValueError("Desktop reauthentication cap must cover the recovery window")
        if self.management_reauthentication_days < self.management_recovery_days:
            raise ValueError("Management reauthentication cap must cover recovery window")
        if self.management_client_id in {self.web_client_id, self.desktop_client_id}:
            raise ValueError("Management client must be independent of Web and desktop")
        from urllib.parse import urlsplit

        for value in (self.app_url, self.oidc_issuer):
            parsed = urlsplit(value)
            if parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
            ):
                raise ValueError("Public origins require HTTPS outside loopback development")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("Invalid public origin")
        if self.session_encryption_key:
            from cryptography.fernet import Fernet

            try:
                Fernet(self.session_encryption_key.get_secret_value().encode())
            except (ValueError, TypeError):
                raise ValueError("Invalid session encryption key configuration") from None
        return self
