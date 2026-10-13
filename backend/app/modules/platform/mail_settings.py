"""Resolve mail settings without mutating the shared provider or exposing its secrets."""

from pydantic import SecretStr

from app.core.config import Settings
from app.modules.auth.oidc import IdentityProvider
from app.modules.platform.branding import public_branding
from app.modules.platform.schemas import MailSettingsView
from app.modules.tenants.models import Installation


def effective_mail(identity: IdentityProvider, install: Installation | None) -> Settings:
    settings = identity.settings.model_copy()
    if install:
        settings.smtp_display_name = install.platform_name or "Actvero"
        brand = public_branding(settings.app_url, install)
        settings.smtp_logo_url = (
            brand.assets.get("wordmark_light")
            or brand.assets.get("mark_light")
            or f"{settings.app_url}/brand/actvero-icon.png"
        )
        settings.smtp_logo_is_wordmark = bool(brand.assets.get("wordmark_light"))
    if install and install.platform_mail_ciphertext:
        value = identity.unseal(install.platform_mail_ciphertext)
        settings.smtp_host = value["host"] if value["enabled"] else None
        settings.smtp_port = value["port"]
        settings.smtp_from = value["sender"]
        settings.smtp_username = value["username"] or None
        settings.smtp_password = SecretStr(value["password"]) if value.get("password") else None
        settings.smtp_starttls = value["security"] == "starttls"
        settings.smtp_ssl = value["security"] == "tls"
    return settings


def mail_view(identity: IdentityProvider, install: Installation) -> MailSettingsView:
    settings = effective_mail(identity, install)
    if install.platform_mail_ciphertext:
        value = identity.unseal(install.platform_mail_ciphertext)
        return MailSettingsView(
            **{
                key: value[key]
                for key in ("enabled", "host", "port", "security", "username", "sender")
            },
            source="platform",
            password_set=bool(value.get("password")),
        )
    return MailSettingsView(
        enabled=bool(settings.smtp_host and settings.smtp_from),
        source="environment",
        host=settings.smtp_host or "",
        port=settings.smtp_port,
        security="tls" if settings.smtp_ssl else ("starttls" if settings.smtp_starttls else "none"),
        username=settings.smtp_username or "",
        sender=settings.smtp_from or "",
        password_set=bool(settings.smtp_password),
    )
