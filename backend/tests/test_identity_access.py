"""Real PostgreSQL isolation/concurrency tests; identity provider is a test double.

Set ACTVERO_TEST_DATABASE_URL explicitly. Each test owns a random schema and never
truncates application tables. Real Keycloak browser verification is separate.
"""

import asyncio
import os
import secrets
import time
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import models  # noqa: F401
from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from app.modules.audit.models import AuditEvent
from app.modules.auth.models import WebSession
from app.modules.auth.service import COOKIE, digest, now
from app.modules.experts.categories import seed_categories as seed_expert_categories
from app.modules.members.models import Invitation, Membership
from app.modules.skills.categories import seed_categories
from app.modules.tenants.models import Installation, Tenant
from app.modules.users.models import LoginIdentity, User

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def env(tmp_path):
    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required for PostgreSQL integration tests")
    schema = "test_identity_" + uuid4().hex
    owner = create_async_engine(url)
    async with owner.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        app_url="http://127.0.0.1:5194",
        session_cookie_name=COOKIE,
        llm_outbox_dir=tmp_path / "llm-outbox",
        platform_edition="community",
        database_url=None,
        session_encryption_key=Fernet.generate_key().decode(),
        smtp_host="test",
        smtp_from="test@example.com",
        invitation_hours=24,
        provisioner_client_secret="test-only",
    )
    app = create_app(settings)
    clients = []
    try:
        async with app.router.lifespan_context(app):
            app.state.database.sessions = sessions
            app.state.database.engine = engine
            provider = app.state.identity_provider
            provider.configure_mail = AsyncMock()
            provider.verify_email = AsyncMock()
            provider.verified_email = AsyncMock(return_value=False)
            provider.inspect = AsyncMock()
            provider.user_enabled = AsyncMock(return_value=True)
            provider.prepare_user = AsyncMock(return_value=("new-subject", False))
            async with sessions() as db:
                db.add(Installation(id=1))
                await db.commit()

            async def client(role="administrator", tenant=None, email=None, joined=True):
                async with sessions() as db:
                    user = User(name="测试成员", email=email or f"{uuid4().hex}@example.com")
                    db.add(user)
                    if joined:
                        tenant = tenant or await db.scalar(select(Tenant))
                        if tenant is None:
                            tenant = Tenant(name="测试组织")
                            db.add(tenant)
                            await db.flush()
                            seed_categories(db, tenant.id)
                            seed_expert_categories(db, tenant.id)
                        await db.flush()
                        installation = await db.get(Installation, 1)
                        installation.tenant_id = tenant.id
                    else:
                        await db.flush()
                    identity = LoginIdentity(
                        user_id=user.id,
                        issuer=settings.oidc_issuer,
                        subject=uuid4().hex,
                        email_verified=True,
                    )
                    db.add(identity)
                    await db.flush()
                    member = (
                        Membership(
                            tenant_id=tenant.id,
                            user_id=user.id,
                            role=role,
                            source="invitation",
                        )
                        if joined
                        else None
                    )
                    raw = secrets.token_urlsafe(32)
                    session = WebSession(
                        token_hash=digest(raw),
                        csrf=secrets.token_urlsafe(32),
                        identity_id=identity.id,
                        authenticated_at=now(),
                        tokens=provider.seal(
                            {"access_token": "test", "expires_at": time.time() + 900}
                        ),
                        expires_at=now() + timedelta(hours=1),
                    )
                    db.add(session)
                    if member:
                        db.add(member)
                    await db.commit()
                api = httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url=settings.app_url,
                    cookies={COOKIE: raw},
                    headers={"origin": settings.app_url, "x-csrf-token": session.csrf},
                )
                clients.append(api)
                return SimpleNamespace(
                    api=api,
                    user=user,
                    member=member,
                    tenant=tenant,
                    identity=identity,
                    session=session,
                    path=f"/api/v1/enterprises/{tenant.id}" if tenant else "",
                )

            yield SimpleNamespace(app=app, sessions=sessions, provider=provider, client=client)
    finally:
        for client in clients:
            await client.aclose()
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()


async def test_anonymous_csrf_and_member_role_are_denied(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    assert (await member.api.get(admin.path + "/members")).status_code == 403
    assert (await member.api.get(admin.path + "/events")).status_code == 403
    path = admin.path + f"/members/{member.member.id}"
    for headers in [{"origin": "https://evil.example"}, {"x-csrf-token": "wrong"}]:
        r = await admin.api.patch(path, json={"action": "pause", "version": 1}, headers=headers)
        assert r.status_code == 403
    admin.api.cookies.clear()
    assert (await admin.api.get(admin.path + "/members")).status_code == 401


async def test_foreign_organization_reads_writes_and_outsiders_are_closed(env):
    first = await env.client()
    outsider = await env.client(joined=False)
    foreign = "/api/v1/enterprises/" + str(uuid4())
    for endpoint in ("members", "invitations", "events"):
        assert (await first.api.get(foreign + "/" + endpoint)).status_code == 403
        assert (await outsider.api.get(first.path + "/" + endpoint)).status_code == 403
    assert (await first.api.get(first.path + f"/members/{uuid4()}")).status_code == 404
    response = await first.api.post(
        foreign + "/invitations", json={"email": "new@example.com", "request_id": str(uuid4())}
    )
    assert response.status_code == 403
    assert not env.provider.prepare_user.called


async def test_database_refuses_second_organization(env):
    await env.client()
    async with env.sessions() as db:
        db.add(Tenant(name="第二个组织"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_simultaneous_admin_self_demotions_keep_one_effective_admin(env):
    one = await env.client()
    two = await env.client(tenant=one.tenant)
    responses = await asyncio.gather(
        *[
            c.api.patch(
                c.path + f"/members/{c.member.id}",
                json={
                    "action": "role",
                    "role": "member",
                    "version": 1,
                },
            )
            for c in (one, two)
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    async with env.sessions() as db:
        members = (await db.scalars(select(Membership))).all()
        assert sum(m.role == "administrator" and m.status == "active" for m in members) == 1
        assert len((await db.scalars(select(AuditEvent))).all()) == 1


async def test_disabled_upstream_admin_does_not_count_as_backup(env):
    one = await env.client()
    await env.client(tenant=one.tenant)
    env.provider.user_enabled.return_value = False
    result = await one.api.patch(
        one.path + f"/members/{one.member.id}",
        json={
            "action": "remove",
            "version": 1,
        },
    )
    assert result.status_code == 409


async def test_pause_restore_requires_fresh_login_and_stale_changes_fail(env):
    admin = await env.client()
    peer = await env.client(tenant=admin.tenant)
    path = admin.path + f"/members/{peer.member.id}"
    assert (await admin.api.patch(path, json={"action": "pause", "version": 1})).status_code == 200
    assert (await peer.api.get(peer.path + "/members")).status_code == 403
    assert (
        await admin.api.patch(path, json={"action": "restore", "version": 1})
    ).status_code == 409
    assert (
        await admin.api.patch(path, json={"action": "restore", "version": 2})
    ).status_code == 200
    assert (await peer.api.get(peer.path + "/members")).status_code == 401
    async with env.sessions() as db:
        session = await db.get(WebSession, peer.session.id)
        session.authenticated_at = now()
        await db.commit()
    assert (await peer.api.get(peer.path + "/members")).status_code == 200


async def invitation(env, admin, recipient):
    token = secrets.token_urlsafe(32)
    async with env.sessions() as db:
        row = Invitation(
            tenant_id=admin.tenant.id,
            email=recipient.user.email,
            subject=recipient.identity.subject,
            token_hash=digest(token),
            token_ciphertext=env.provider.seal({"token": token}),
            created_by=admin.user.id,
            expires_at=now() + timedelta(hours=1),
        )
        db.add(row)
        await db.commit()
    assert (
        await recipient.api.post("/api/v1/invitations/claim", json={"token": token})
    ).status_code == 200
    return row, token


async def test_invite_subject_binding_idempotency_and_no_removed_member_revival(env):
    admin, recipient, wrong = (
        await env.client(),
        await env.client(joined=False),
        await env.client(joined=False),
    )
    row, token = await invitation(env, admin, recipient)
    await wrong.api.post("/api/v1/invitations/claim", json={"token": token})
    assert (await wrong.api.get("/api/v1/invitations/current")).json() == {
        "state": "mismatch",
        "activation_required": False,
        "role": "member",
        "tenant_name": None,
        "email": None,
        "expires_at": None,
    }
    assert (await wrong.api.post("/api/v1/invitations/accept")).status_code == 403
    results = await asyncio.gather(
        *[recipient.api.post("/api/v1/invitations/accept") for _ in range(2)]
    )
    assert all(r.status_code == 200 for r in results)
    async with env.sessions() as db:
        member = await db.scalar(
            select(Membership).where(
                Membership.tenant_id == admin.tenant.id,
                Membership.user_id == recipient.user.id,
            )
        )
        member.status = "removed"
        await db.commit()
    assert (await recipient.api.post("/api/v1/invitations/accept")).status_code == 409


async def test_resend_invalidates_already_claimed_invitation(env, monkeypatch):
    admin, recipient = await env.client(), await env.client(joined=False)
    row, token = await invitation(env, admin, recipient)
    mail = AsyncMock()
    monkeypatch.setattr("app.modules.members.invitations.send_invitation", mail)
    result = await admin.api.post(
        admin.path + f"/invitations/{row.id}/delivery",
        json={
            "request_id": str(uuid4()),
            "replace": True,
        },
    )
    assert result.status_code == 200
    assert (await recipient.api.post("/api/v1/invitations/accept")).status_code == 409
    assert (
        await recipient.api.post("/api/v1/invitations/claim", json={"token": token})
    ).status_code == 404
    new_token = mail.call_args.args[3]
    await recipient.api.post("/api/v1/invitations/claim", json={"token": new_token})
    assert (await recipient.api.post("/api/v1/invitations/accept")).status_code == 200


async def test_mail_failure_is_queryable_and_retry_is_idempotent(env, monkeypatch):
    admin = await env.client()
    mail = AsyncMock(side_effect=OSError("SMTP offline"))
    monkeypatch.setattr("app.modules.members.invitations.send_invitation", mail)
    request_id = str(uuid4())
    payload = {"email": "new@example.com", "request_id": request_id}
    result = await admin.api.post(admin.path + "/invitations", json=payload)
    assert result.status_code == 200 and result.json()["mail_status"] == "failed"
    assert (await admin.api.post(admin.path + "/invitations", json=payload)).json() == result.json()
    assert mail.call_count == 1
    mail.side_effect = None
    retry_id = str(uuid4())
    path = admin.path + f"/invitations/{request_id}/delivery"
    sent = await admin.api.post(path, json={"request_id": retry_id})
    assert sent.json()["mail_status"] == "submitted"
    assert (await admin.api.post(path, json={"request_id": retry_id})).json() == sent.json()
    assert mail.call_count == 2
    assert (
        await admin.api.post(admin.path + f"/invitations/{request_id}/revoke")
    ).status_code == 200
    assert (await admin.api.post(path, json={"request_id": str(uuid4())})).status_code == 409


async def test_login_callback_rejects_bad_state_invalid_claims_and_replay(env, caplog):
    from joserfc.errors import InvalidClaimError

    user = await env.client()
    state = secrets.token_urlsafe(32)
    async with env.sessions() as db:
        row = await db.get(WebSession, user.session.id)
        row.login_state = digest(state)
        row.login_data = env.provider.seal({"nonce": "nonce", "verifier": "verifier", "next": "/"})
        row.login_expires_at = now() + timedelta(minutes=10)
        await db.commit()
    env.provider.exchange = AsyncMock(side_effect=InvalidClaimError("nonce"))
    result = await user.api.get("/api/v1/auth/callback", params={"state": "bad", "code": "test"})
    assert result.status_code == 303
    assert not env.provider.exchange.called
    assert "state_mismatch; session_cookie_present=True" in caplog.text
    assert state not in caplog.text
    assert user.api.cookies.get(COOKIE) not in caplog.text
    result = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert result.status_code == 303 and result.headers["location"] == "/login?error=callback"
    result = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert result.status_code == 303
    assert env.provider.exchange.call_count == 1


async def test_callback_missing_cookie_is_rejected_and_logged_without_code_or_state(env, caplog):
    user = await env.client()
    user.api.cookies.clear()
    env.provider.exchange = AsyncMock()
    state, code = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    result = await user.api.get("/api/v1/auth/callback", params={"state": state, "code": code})
    assert result.status_code == 303
    assert result.headers["location"] == "/login?error=callback"
    assert "missing_session; session_cookie_present=False" in caplog.text
    assert state not in caplog.text and code not in caplog.text
    env.provider.exchange.assert_not_called()


async def test_expired_invitation_cannot_replace_a_newer_pending_one(env, monkeypatch):
    admin, recipient = await env.client(), await env.client(joined=False)
    old, _ = await invitation(env, admin, recipient)
    async with env.sessions() as db:
        row = await db.get(Invitation, old.id)
        row.status = "expired"
        row.expires_at = now() - timedelta(hours=1)
        await db.commit()
    await invitation(env, admin, recipient)
    mail = AsyncMock()
    monkeypatch.setattr("app.modules.members.invitations.send_invitation", mail)
    response = await admin.api.post(
        admin.path + f"/invitations/{old.id}/delivery",
        json={
            "request_id": str(uuid4()),
            "replace": True,
        },
    )
    assert response.status_code == 409
    assert not mail.called


async def anonymous_browser(env):
    browser = await env.client(joined=False)
    async with env.sessions() as db:
        session = await db.get(WebSession, browser.session.id)
        session.identity_id = None
        session.tokens = None
        await db.commit()
    return browser


def registration_payload(email="admin@example.com"):
    return {
        "organization_name": "唯一组织",
        "name": "首位管理员",
        "email": email,
        "password": "test-password-only",
    }


async def begin_login(env, browser):
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    result = await browser.api.get("/api/v1/auth/login", params={"switch": "true"})
    assert result.status_code == 307
    return env.provider.authorization.call_args.args[0]


def exchange_as(env, subject, email="admin@example.com"):
    env.provider.exchange = AsyncMock(
        return_value=(
            {"access_token": "test", "expires_at": time.time() + 900},
            {"sub": subject, "name": "首位管理员", "email": email, "email_verified": False},
        )
    )


async def test_registration_is_anonymous_but_requires_origin_and_csrf(env):
    browser = await anonymous_browser(env)
    env.provider.create_initial_user = AsyncMock(return_value="registered-admin")
    for headers in [{"origin": "https://evil.example"}, {"x-csrf-token": "wrong"}]:
        response = await browser.api.post(
            "/api/v1/setup/register", json=registration_payload(), headers=headers
        )
        assert response.status_code == 403
    assert not env.provider.create_initial_user.called
    response = await browser.api.post("/api/v1/setup/register", json=registration_payload())
    assert response.status_code == 200
    view = (await browser.api.get("/api/v1/auth/session")).json()
    assert view["setup_account_created"] is True
    assert view["setup_complete"] is False
    assert view["authenticated"] is False
    assert view["organization"] is None
    assert "setup_verified" not in view
    assert "test-password-only" not in response.text
    async with env.sessions() as db:
        assert not (await db.scalars(select(Tenant))).all()
        assert not (await db.scalars(select(Membership))).all()
    for path in ("verify", "complete"):
        assert (await browser.api.post("/api/v1/setup/" + path, json={})).status_code in (404, 405)


async def test_concurrent_registration_reserves_one_identity_and_cannot_replace_it(env):
    one, two = await anonymous_browser(env), await anonymous_browser(env)
    env.provider.create_initial_user = AsyncMock(return_value="registered-admin")
    responses = await asyncio.gather(
        one.api.post("/api/v1/setup/register", json=registration_payload("one@example.com")),
        two.api.post("/api/v1/setup/register", json=registration_payload("two@example.com")),
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert env.provider.create_initial_user.call_count == 1
    assert (
        await two.api.post("/api/v1/setup/register", json=registration_payload("other@example.com"))
    ).status_code == 409
    assert env.provider.create_initial_user.call_count == 1
    async with env.sessions() as db:
        install = await db.get(Installation, 1)
        assert install.subject == "registered-admin"
        assert install.organization_name == "唯一组织"


async def test_valid_admin_login_from_another_browser_finishes_setup_once(env):
    registration = await anonymous_browser(env)
    env.provider.create_initial_user = AsyncMock(return_value="registered-admin")
    assert (
        await registration.api.post("/api/v1/setup/register", json=registration_payload())
    ).status_code == 200
    one, two = await anonymous_browser(env), await anonymous_browser(env)
    states = [await begin_login(env, browser) for browser in (one, two)]
    exchange_as(env, "registered-admin")
    responses = await asyncio.gather(
        *[
            browser.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
            for browser, state in zip((one, two), states, strict=True)
        ]
    )
    assert all(r.status_code == 303 and r.headers["location"] == "/console" for r in responses)
    for browser in (one, two):
        view = (await browser.api.get("/api/v1/auth/session")).json()
        assert view["authenticated"] and view["setup_complete"]
        assert view["organization"]["role"] == "administrator"
        assert view["organization"]["name"] == "唯一组织"
    async with env.sessions() as db:
        assert len((await db.scalars(select(Tenant))).all()) == 1
        assert len((await db.scalars(select(Membership))).all()) == 1
        assert len((await db.scalars(select(AuditEvent))).all()) == 1
    # A subsequent login must not promote an existing member or recreate the organization.
    async with env.sessions() as db:
        member = await db.scalar(select(Membership))
        member.role = "member"
        await db.commit()
    state = await begin_login(env, one)
    await one.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    view = (await one.api.get("/api/v1/auth/session")).json()
    assert view["organization"]["role"] == "member"


@pytest.mark.parametrize("mismatch", ["subject", "issuer", "invalid_token", "cancelled"])
async def test_setup_never_promotes_wrong_or_unverified_login(env, mismatch):
    from fastapi import HTTPException

    browser = await anonymous_browser(env)
    env.provider.create_initial_user = AsyncMock(return_value="registered-admin")
    await browser.api.post("/api/v1/setup/register", json=registration_payload())
    if mismatch == "issuer":
        async with env.sessions() as db:
            install = await db.get(Installation, 1)
            install.issuer = "https://another-issuer.test"
            await db.commit()
    state = await begin_login(env, browser)
    # Even the same email cannot replace the reserved subject or issuer.
    exchange_as(env, "other-subject" if mismatch == "subject" else "registered-admin")
    if mismatch == "invalid_token":
        env.provider.inspect = AsyncMock(side_effect=HTTPException(401, "invalid"))
    params = {"state": state, "code": "test"}
    if mismatch == "cancelled":
        params = {"state": state, "error": "access_denied"}
    response = await browser.api.get("/api/v1/auth/callback", params=params)
    assert response.status_code == 303
    async with env.sessions() as db:
        assert not (await db.scalars(select(Tenant))).all()
        assert not (await db.scalars(select(Membership))).all()


async def test_registration_retry_keeps_internal_marker_and_validation_hides_password(env):
    from fastapi import HTTPException

    browser = await anonymous_browser(env)
    env.provider.create_initial_user = AsyncMock(side_effect=HTTPException(503, "try again"))
    response = await browser.api.post("/api/v1/setup/register", json=registration_payload())
    assert response.status_code == 503
    marker = env.provider.create_initial_user.call_args.args[3]
    env.provider.create_initial_user.side_effect = None
    env.provider.create_initial_user.return_value = "registered-admin"
    response = await browser.api.post("/api/v1/setup/register", json=registration_payload())
    assert response.status_code == 200
    assert env.provider.create_initial_user.call_args.args[3] == marker
    assert marker not in response.text
    response = await browser.api.post(
        "/api/v1/setup/register",
        json={**registration_payload(), "email": "invalid", "password": "must-not-appear"},
    )
    assert response.status_code == 422 and "must-not-appear" not in response.text


async def test_profile_changes_only_self_and_survives_identity_refresh(env):
    admin = await env.client()
    member = await env.client(role="member")
    changed = await member.api.patch("/api/v1/account/profile", json={"name": "  我的新名字  "})
    assert changed.status_code == 200
    assert changed.json()["name"] == "我的新名字"
    for payload in [
        {"name": " "},
        {"name": "bad\nname"},
        {"name": "伪造", "user_id": str(admin.user.id)},
        {"name": "伪造", "role": "administrator"},
    ]:
        assert (await member.api.patch("/api/v1/account/profile", json=payload)).status_code == 422
    state = await begin_login(env, member)
    exchange_as(env, member.identity.subject, member.user.email)
    result = await member.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    assert result.status_code == 303
    view = (await member.api.get("/api/v1/auth/session")).json()
    assert view["user"]["name"] == "我的新名字"
    assert view["organization"]["role"] == "member"
    async with env.sessions() as db:
        assert (await db.get(User, admin.user.id)).name == "测试成员"
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "account.profile"))
        assert event.actor_id == member.user.id and event.target_id == member.user.id


async def test_account_requires_membership_and_csrf(env):
    admin, member, outsider = (
        await env.client(),
        await env.client(role="member"),
        await env.client(joined=False),
    )
    for headers in [{"origin": "https://evil.example"}, {"x-csrf-token": "wrong"}]:
        assert (
            await member.api.patch(
                "/api/v1/account/profile", json={"name": "拒绝"}, headers=headers
            )
        ).status_code == 403
        assert (
            await member.api.delete("/api/v1/account/avatar", headers=headers)
        ).status_code == 403
        assert (await member.api.post("/api/v1/auth/password", headers=headers)).status_code == 403
    for method, path, kwargs in [
        ("PATCH", "/api/v1/account/profile", {"json": {"name": "拒绝"}}),
        (
            "PUT",
            "/api/v1/account/avatar",
            {"content": b"invalid", "headers": {"content-type": "image/png"}},
        ),
        ("GET", "/api/v1/account/avatar", {}),
        ("POST", "/api/v1/auth/password", {}),
    ]:
        assert (await outsider.api.request(method, path, **kwargs)).status_code == 403
    await admin.api.patch(
        admin.path + f"/members/{member.member.id}", json={"action": "pause", "version": 1}
    )
    assert (
        await member.api.patch("/api/v1/account/profile", json={"name": "拒绝"})
    ).status_code == 403
    assert (await member.api.get("/api/v1/account/avatar")).status_code == 403
    member.api.cookies.clear()
    assert (await member.api.get("/api/v1/account/avatar")).status_code == 401


async def test_avatar_reencodes_isolates_and_removes(env):
    from io import BytesIO

    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    one, two = await env.client(role="member"), await env.client(role="member")
    output = BytesIO()
    metadata = PngInfo()
    metadata.add_text("private", "must be stripped")
    Image.new("RGB", (400, 200), "red").save(output, format="PNG", pnginfo=metadata)
    uploaded = await one.api.put(
        "/api/v1/account/avatar", content=output.getvalue(), headers={"content-type": "image/png"}
    )
    assert uploaded.status_code == 200
    url = uploaded.json()["avatar_url"]
    downloaded = await one.api.get(url)
    assert downloaded.headers["content-type"] == "image/webp"
    assert "no-store" in downloaded.headers["cache-control"]
    with Image.open(BytesIO(downloaded.content)) as image:
        assert image.format == "WEBP" and image.size == (256, 256)
        assert "private" not in image.info and "exif" not in image.info
    assert (await two.api.get(url)).status_code == 404
    assert (await two.api.get(url + "&user_id=" + str(one.user.id))).status_code == 404
    assert (await one.api.delete("/api/v1/account/avatar")).json()["avatar_url"] is None
    assert (await one.api.get(url)).status_code == 404
    async with env.sessions() as db:
        assert await db.scalar(select(User.avatar_data).where(User.id == one.user.id)) is None


async def test_avatar_rejects_invalid_large_or_animated_images(env):
    from io import BytesIO

    from PIL import Image

    browser = await env.client()
    for kind, content, status in [
        ("image/svg+xml", b"<svg/>", 415),
        ("image/png", b"not an image", 422),
        ("image/png", b"x" * (2 * 1024 * 1024 + 1), 413),
    ]:
        assert (
            await browser.api.put(
                "/api/v1/account/avatar", content=content, headers={"content-type": kind}
            )
        ).status_code == status
    for image, options in [
        (Image.new("RGB", (4001, 4000)), {}),
        (
            Image.new("RGB", (10, 10), "red"),
            {"save_all": True, "append_images": [Image.new("RGB", (10, 10), "blue")]},
        ),
    ]:
        content = BytesIO()
        image.save(content, format="PNG", **options)
        assert (
            await browser.api.put(
                "/api/v1/account/avatar",
                content=content.getvalue(),
                headers={"content-type": "image/png"},
            )
        ).status_code == 422
    assert (await browser.api.get("/api/v1/account/avatar")).status_code == 404


async def test_logout_rotates_session_and_requires_fresh_login(env):
    browser = await env.client()
    original_cookie = browser.api.cookies.get(COOKIE)
    assert (await browser.api.post("/api/v1/auth/logout")).status_code == 200
    browser.api.cookies.delete(COOKIE, domain="", path="/")
    assert browser.api.cookies.get(COOKIE) != original_cookie
    view = (await browser.api.get("/api/v1/auth/session")).json()
    assert not view["authenticated"] and view["user"] is None
    assert view["csrf"] != browser.session.csrf
    env.provider.authorization = AsyncMock(return_value="https://identity.test/login")
    await browser.api.get("/api/v1/auth/login")
    assert env.provider.authorization.call_args.args[3] is True
    state = env.provider.authorization.call_args.args[0]
    exchange_as(env, browser.identity.subject)
    await browser.api.get("/api/v1/auth/callback", params={"state": state, "code": "test"})
    await browser.api.get("/api/v1/auth/login")
    assert env.provider.authorization.call_args.args[3] is False
    async with env.sessions() as db:
        assert await db.get(WebSession, browser.session.id) is None


@pytest.mark.parametrize("outcome", ["success", "cancelled", "wrong_account", "error"])
async def test_password_action_binds_account_and_handles_cancel(env, outcome):
    browser = await env.client(role="member")
    env.provider.authorization = AsyncMock(return_value="https://identity.test/password")
    response = await browser.api.post("/api/v1/auth/password")
    assert response.status_code == 200
    assert response.json()["url"] == "https://identity.test/password"
    assert env.provider.authorization.call_args.kwargs == {"password": True}
    state = env.provider.authorization.call_args.args[0]
    exchange_as(env, "other-subject" if outcome == "wrong_account" else browser.identity.subject)
    params = {"state": state, "code": "test"}
    if outcome == "cancelled":
        params["kc_action_status"] = "cancelled"
    if outcome == "error":
        params = {"state": state, "error": "access_denied"}
    response = await browser.api.get("/api/v1/auth/callback", params=params)
    assert response.status_code == 303
    expected = "/account?tab=security"
    if outcome in {"cancelled", "error"}:
        expected += "&password=cancelled"
    elif outcome == "wrong_account":
        expected += "&password=error"
    assert response.headers["location"] == expected
    view = (await browser.api.get("/api/v1/auth/session")).json()
    assert view["user"]["id"] == str(browser.user.id)
    async with env.sessions() as db:
        assert len((await db.scalars(select(User))).all()) == 1


def direct_member_payload(**changes):
    return {
        "request_id": str(uuid4()),
        "name": "新成员",
        "email": "direct@example.com",
        "password": " test-only-password ",
        **changes,
    }


async def test_direct_creation_maps_identity_and_login_without_invitation(env):
    from app.modules.members.models import MemberCreation

    admin = await env.client()
    env.provider.create_member_user = AsyncMock(return_value=("direct-subject", False))
    payload = direct_member_payload(name="  新成员  ")
    response = await admin.api.post(admin.path + "/members", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["member"]["role"] == "member"
    assert result["member"]["source"] == "direct"
    assert result["member"]["name"] == "新成员"
    assert result["initial_password_reused"] is False
    assert payload["password"] not in response.text
    assert env.provider.create_member_user.call_args.args[:3] == (
        "direct@example.com",
        "新成员",
        payload["password"],
    )
    async with env.sessions() as db:
        operation = await db.scalar(select(MemberCreation))
        assert str(operation.member_id) == result["member"]["id"]
        identity = await db.scalar(
            select(LoginIdentity).where(LoginIdentity.subject == "direct-subject")
        )
        assert identity.issuer == env.provider.settings.oidc_issuer
        assert identity.email_verified is False
        event = await db.scalar(select(AuditEvent).where(AuditEvent.action == "member.created"))
        assert event.details == {"role": "member", "source": "direct"}
        assert payload["password"] not in str(operation.__dict__) + str(event.__dict__)
        assert not (await db.scalars(select(Invitation))).all()
    browser = await anonymous_browser(env)
    state = await begin_login(env, browser)
    exchange_as(env, "direct-subject", "direct@example.com")
    callback = await browser.api.get(
        "/api/v1/auth/callback", params={"state": state, "code": "test"}
    )
    assert callback.status_code == 303
    view = (await browser.api.get("/api/v1/auth/session")).json()
    assert view["organization"]["role"] == "member"
    assert view["organization"]["status"] == "active"


async def test_direct_create_guards_and_validation_do_not_reach_provider(env):
    admin = await env.client()
    member = await env.client(role="member")
    outsider = await env.client(joined=False)
    env.provider.create_member_user = AsyncMock()
    payload = direct_member_payload()
    path = admin.path + "/members"
    for client in (member, outsider):
        assert (await client.api.post(path, json=payload)).status_code == 403
    assert (
        await admin.api.post(f"/api/v1/enterprises/{uuid4()}/members", json=payload)
    ).status_code == 403
    for headers in ({"origin": "https://evil.example"}, {"x-csrf-token": "wrong"}):
        assert (await admin.api.post(path, json=payload, headers=headers)).status_code == 403
    for changes in ({"role": "owner"}, {"password": "short"}, {"name": "   "}):
        result = await admin.api.post(path, json={**payload, **changes})
        assert result.status_code == 422
        assert "short" not in result.text
    admin.api.cookies.clear()
    assert (
        await admin.api.post(path, json=payload)
    ).status_code == 403  # Mutation requires a browser session.
    env.provider.create_member_user.assert_not_called()


async def test_direct_create_concurrent_replay_and_duplicate_do_not_restore_or_escalate(env):
    from app.modules.members.models import MemberCreation

    admin = await env.client()
    env.provider.create_member_user = AsyncMock(return_value=("direct-subject", False))
    payload = direct_member_payload()
    path = admin.path + "/members"
    results = await asyncio.gather(*[admin.api.post(path, json=payload) for _ in range(2)])
    assert [r.status_code for r in results] == [200, 200]
    assert len({r.json()["member"]["id"] for r in results}) == 1
    assert env.provider.create_member_user.call_count == 1
    assert (
        await admin.api.post(path, json={**payload, "role": "administrator"})
    ).status_code == 409
    assert (
        await admin.api.post(path, json={**payload, "request_id": str(uuid4())})
    ).status_code == 409
    async with env.sessions() as db:
        operation = await db.scalar(select(MemberCreation))
        member = await db.get(Membership, operation.member_id)
        member.status = "removed"
        await db.commit()
    replay = await admin.api.post(path, json=payload)
    assert replay.json()["member"]["status"] == "removed"
    assert replay.json()["member"]["role"] == "member"
    assert env.provider.create_member_user.call_count == 1
    async with env.sessions() as db:
        assert (
            len(
                (
                    await db.scalars(
                        select(AuditEvent).where(AuditEvent.action == "member.created")
                    )
                ).all()
            )
            == 1
        )


async def test_direct_create_uncertain_failure_retains_marker_and_blocks_invitation(env):
    from app.modules.members.models import MemberCreation

    admin = await env.client()
    env.provider.create_member_user = AsyncMock(side_effect=httpx.ReadTimeout("test-only"))
    payload = direct_member_payload(role="administrator")
    path = admin.path + "/members"
    assert (await admin.api.post(path, json=payload)).status_code == 503
    marker = env.provider.create_member_user.call_args.args[3]
    invite = await admin.api.post(
        admin.path + "/invitations",
        json={"request_id": str(uuid4()), "email": payload["email"], "name": payload["name"]},
    )
    assert invite.status_code == 409
    env.provider.prepare_user.assert_not_called()
    async with env.sessions() as db:
        operation = await db.scalar(select(MemberCreation))
        assert operation.marker == marker
        assert operation.member_id is None
    env.provider.create_member_user.side_effect = None
    env.provider.create_member_user.return_value = ("recovered-subject", True)
    retry = await admin.api.post(path, json={**payload, "request_id": str(uuid4())})
    assert retry.status_code == 200, retry.text
    assert retry.json()["initial_password_reused"] is True
    assert retry.json()["member"]["role"] == "administrator"
    assert env.provider.create_member_user.call_args.args[3] == marker


@pytest.mark.parametrize("status", [409, 422])
async def test_direct_create_definite_rejection_releases_pending_reservation(env, status):
    from fastapi import HTTPException

    from app.modules.members.models import MemberCreation

    admin = await env.client()
    env.provider.create_member_user = AsyncMock(side_effect=HTTPException(status, "test rejection"))
    payload = direct_member_payload()
    assert (await admin.api.post(admin.path + "/members", json=payload)).status_code == status
    async with env.sessions() as db:
        assert not (await db.scalars(select(MemberCreation))).all()
        assert len((await db.scalars(select(Membership))).all()) == 1
    env.provider.create_member_user.side_effect = None
    env.provider.create_member_user.return_value = ("new-subject", False)
    assert (await admin.api.post(admin.path + "/members", json=payload)).status_code == 200


async def test_direct_create_refuses_existing_members_and_pending_invitations(env):
    admin = await env.client()
    recipient = await env.client(joined=False)
    env.provider.create_member_user = AsyncMock()
    await invitation(env, admin, recipient)
    for email in (admin.user.email, recipient.user.email):
        response = await admin.api.post(
            admin.path + "/members", json=direct_member_payload(email=email)
        )
        assert response.status_code == 409
    env.provider.create_member_user.assert_not_called()
