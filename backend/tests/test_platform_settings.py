import io
import smtplib
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select
from test_identity_access import env  # noqa: F401

from app.modules.auth.service import digest, now
from app.modules.members.mail import (
    compose_mail,
    compose_member_invitation,
    compose_organization_invitation,
)
from app.modules.platform.mail_settings import effective_mail
from app.modules.tenants.models import Installation, OrganizationInvitation, PlatformOperator

pytestmark = pytest.mark.asyncio


async def operator(env):  # noqa: F811
    env.provider.settings.platform_edition = "saas"
    actor = await env.client(joined=False)
    async with env.sessions() as db:
        db.add(PlatformOperator(user_id=actor.user.id))
        await db.commit()
    return actor


async def test_platform_scope_and_csrf(env):  # noqa: F811
    admin = await env.client()
    assert (await admin.api.get("/api/v1/platform/settings")).status_code == 404
    env.provider.settings.platform_edition = "saas"
    assert (await admin.api.get("/api/v1/platform/settings")).status_code == 403
    actor = await operator(env)
    assert (await actor.api.get("/api/v1/platform/settings")).json()["platform_name"] == "Actvero"
    assert (
        await actor.api.put(
            "/api/v1/platform/settings",
            json={"platform_name": "Other"},
            headers={"x-csrf-token": "invalid"},
        )
    ).status_code == 403
    assert (await admin.api.put("/api/v1/platform/mail", json=mail_payload())).status_code == 403


async def test_brand_persistence_validation_and_public_session(env):  # noqa: F811
    actor = await operator(env)
    for name in (" ", "\r\nInjected: yes", "x" * 81):
        assert (
            await actor.api.put("/api/v1/platform/settings", json={"platform_name": name})
        ).status_code == 422
    response = await actor.api.put("/api/v1/platform/settings", json={"platform_name": "团队平台"})
    assert response.json()["platform_name"] == "团队平台"
    assert (await actor.api.get("/api/v1/auth/session")).json()["platform_name"] == "团队平台"
    async with env.sessions() as db:
        assert (await db.get(Installation, 1)).platform_name == "团队平台"


async def test_logo_normalized_and_reset_does_not_change_name(env):  # noqa: F811
    actor = await operator(env)
    await actor.api.put("/api/v1/platform/settings", json={"platform_name": "品牌"})
    path = "/api/v1/platform/settings/logo"
    assert (
        await actor.api.put(path, content=b"<svg/>", headers={"content-type": "image/svg+xml"})
    ).status_code == 415
    assert (
        await actor.api.put(path, content=b"not an image", headers={"content-type": "image/png"})
    ).status_code == 422
    assert (
        await actor.api.put(
            path, content=b"x" * (2 * 1024 * 1024 + 1), headers={"content-type": "image/png"}
        )
    ).status_code == 413
    image = io.BytesIO()
    Image.new("RGB", (20, 20), "blue").save(image, format="PNG")
    response = await actor.api.put(
        path, content=image.getvalue(), headers={"content-type": "image/png"}
    )
    assert response.status_code == 200
    assert "/api/v1/platform/logo?v=" in response.json()["logo_url"]
    public = await actor.api.get("/api/v1/platform/logo")
    assert public.headers["content-type"] == "image/webp"
    assert Image.open(io.BytesIO(public.content)).format == "WEBP"
    response = await actor.api.delete(path)
    assert response.json()["logo_url"] is None
    assert response.json()["platform_name"] == "品牌"
    assert (await actor.api.get("/api/v1/platform/logo")).status_code == 404


def mail_payload(**changes):
    return (
        dict(
            enabled=True,
            host="smtp.example.com",
            port=465,
            security="tls",
            username="operator@example.com",
            sender="operator@example.com",
            password="private-auth-code",
        )
        | changes
    )


async def test_mail_secret_encrypted_preserved_and_not_reused_on_new_host(env):  # noqa: F811
    actor = await operator(env)
    response = await actor.api.put("/api/v1/platform/mail", json=mail_payload())
    assert response.status_code == 200
    assert response.json()["password_set"] is True
    assert "private-auth-code" not in response.text
    async with env.sessions() as db:
        install = await db.get(Installation, 1)
        assert "private-auth-code" not in install.platform_mail_ciphertext
        settings = effective_mail(env.provider, install)
        assert settings.smtp_password.get_secret_value() == "private-auth-code"
        assert settings.smtp_ssl and not settings.smtp_starttls
    assert env.provider.settings.smtp_host == "test"
    assert (
        await actor.api.put("/api/v1/platform/mail", json=mail_payload(password=None))
    ).status_code == 200
    assert (
        await actor.api.put(
            "/api/v1/platform/mail", json=mail_payload(host="other.example.com", password=None)
        )
    ).status_code == 422
    assert (
        await actor.api.put("/api/v1/platform/mail", json=mail_payload(port=587, password=None))
    ).status_code == 422
    assert (
        await actor.api.put("/api/v1/platform/mail", json=mail_payload(host="https://example.com"))
    ).status_code == 422
    assert "private-auth-code" not in (await actor.api.get("/api/v1/platform/mail")).text


async def test_mail_test_is_explicit_rate_limited_and_errors_redacted(env):  # noqa: F811
    actor = await operator(env)
    mail = AsyncMock()
    with patch("app.modules.platform.router.send_mail", mail):
        await actor.api.put("/api/v1/platform/mail", json=mail_payload())
        await actor.api.get("/api/v1/platform/mail/preview")
        mail.assert_not_awaited()
        response = await actor.api.post(
            "/api/v1/platform/mail/test", json={"email": "recipient@example.com"}
        )
        assert response.status_code == 200
        assert mail.await_args.args[1]["To"] == "recipient@example.com"
        mail.side_effect = smtplib.SMTPAuthenticationError(535, b"secret diagnostic")
        response = await actor.api.post(
            "/api/v1/platform/mail/test", json={"email": "recipient@example.com"}
        )
        assert response.status_code == 502
        assert "secret diagnostic" not in response.text
        await actor.api.post("/api/v1/platform/mail/test", json={"email": "r@example.com"})
        assert (
            await actor.api.post("/api/v1/platform/mail/test", json={"email": "r@example.com"})
        ).status_code == 429


async def test_disabled_mail_preserves_link_invitation(env):  # noqa: F811
    actor = await operator(env)
    await actor.api.put("/api/v1/platform/mail", json=mail_payload(enabled=False))
    response = await actor.api.post(
        "/api/v1/platform/organization-invitations", json={"expires_in_hours": 24}
    )
    assert response.status_code == 200
    invitation_id = response.json()["invitation"]["id"]
    assert (
        await actor.api.post(f"/api/v1/platform/organization-invitations/{invitation_id}/link")
    ).status_code == 200
    assert (
        await actor.api.post("/api/v1/platform/mail/test", json={"email": "r@example.com"})
    ).status_code == 409


async def test_invitation_mail_checks_expiry_and_revocation(env):  # noqa: F811
    actor = await operator(env)
    invitation_id = uuid4()
    async with env.sessions() as db:
        db.add(
            OrganizationInvitation(
                id=invitation_id,
                created_by=actor.user.id,
                token_hash=digest("secret-link"),
                token_ciphertext=env.provider.seal(
                    {"id": str(invitation_id), "token": "secret-link"}
                ),
                expires_at=now() + timedelta(hours=1),
            )
        )
        await db.commit()
    path = f"/api/v1/platform/organization-invitations/{invitation_id}"
    mail = AsyncMock()
    with patch("app.modules.platform.router.send_mail", mail):
        assert (
            await actor.api.post(path + "/delivery", json={"email": "r@example.com"})
        ).status_code == 200
        message = mail.await_args.args[1]
        assert "secret-link" in message.get_body(preferencelist=("html",)).get_content()
        async with env.sessions() as db:
            row = await db.scalar(select(OrganizationInvitation))
            row.expires_at = now() - timedelta(seconds=1)
            await db.commit()
        assert (
            await actor.api.post(path + "/delivery", json={"email": "r@example.com"})
        ).status_code == 409
        await actor.api.post(path + "/revoke")
        assert (
            await actor.api.post(path + "/delivery", json={"email": "r@example.com"})
        ).status_code == 409
        assert mail.await_count == 1


async def test_html_mail_escapes_brand_and_has_plaintext(env):  # noqa: F811
    settings = env.provider.settings.model_copy(update={"smtp_display_name": "<img src=x>"})
    message = compose_mail(
        settings,
        "r@example.com",
        "<script>alert(1)</script>",
        "组织 <b>测试</b>",
        settings.app_url + "/join#token",
        "打开邀请",
    )
    html = message.get_body(preferencelist=("html",)).get_content()
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "&lt;img src=x&gt;" in html and "&lt;b&gt;" in html
    assert "/join#token" in message.get_body(preferencelist=("plain",)).get_content()


async def test_template_previews_match_delivery_and_enforce_platform_access(env):  # noqa: F811
    actor = await operator(env)
    member = await env.client()
    await actor.api.put("/api/v1/platform/settings", json={"platform_name": "团队品牌"})
    async with env.sessions() as db:
        settings = effective_mail(env.provider, await db.get(Installation, 1))
    messages = {
        "organization_invitation": compose_organization_invitation(
            settings, "preview@example.com", settings.app_url + "/organization-invite#preview"
        ),
        "member_invitation": compose_member_invitation(
            settings, "preview@example.com", "示例组织", settings.app_url + "/join#preview"
        ),
    }
    with patch("app.modules.platform.router.send_mail", AsyncMock()) as send:
        for template, message in messages.items():
            path = "/api/v1/platform/mail/preview?template=" + template
            response = await actor.api.get(path)
            assert response.status_code == 200
            assert response.json() == {
                "subject": str(message["Subject"]),
                "html": message.get_body(preferencelist=("html",)).get_content(),
            }
            assert (await member.api.get(path)).status_code == 403
        default = await actor.api.get("/api/v1/platform/mail/preview")
        assert "组织开通邀请" in default.json()["subject"]
        assert "完成组织开通后，邀请链接将失效" in default.json()["html"]
        assert (
            await actor.api.get("/api/v1/platform/mail/preview?template=unknown")
        ).status_code == 422
        send.assert_not_awaited()
