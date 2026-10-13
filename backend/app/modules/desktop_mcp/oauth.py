"""Upstream authorization is staged; only the initiating native device can attach it."""

import secrets
from datetime import timedelta
from urllib.parse import urlencode
from uuid import UUID

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import digest, now, provider
from app.modules.desktop.errors import fail
from app.modules.desktop.service import pkce
from app.modules.desktop_mcp.models import NativeOAuthAttempt
from app.modules.desktop_mcp.schemas import OAuthAttemptView
from app.modules.desktop_mcp.service import NativeActor, get_service
from app.modules.mcp import credentials
from app.modules.mcp.models import McpService
from app.modules.mcp.network import resolve
from app.modules.members.service import record

ACTIVE = ("pending", "exchanging", "awaiting_confirmation")


def callback_url(request: Request) -> str:
    return provider(request).settings.app_url.rstrip("/") + "/api/v1/desktop/mcp/oauth/callback"


async def cancel_pending(db: AsyncSession, service_id: UUID, member_id: UUID) -> None:
    await db.execute(
        update(NativeOAuthAttempt)
        .where(
            NativeOAuthAttempt.service_id == service_id,
            NativeOAuthAttempt.member_id == member_id,
            NativeOAuthAttempt.status.in_(ACTIVE),
        )
        .values(status="cancelled", verifier=None, pending_tokens=None)
    )


async def lock_service(db: AsyncSession, actor: NativeActor, service_id: UUID) -> McpService:
    await db.scalar(
        select(McpService)
        .where(McpService.id == service_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return await get_service(db, actor, service_id)


def view(attempt: NativeOAuthAttempt, url: str | None = None) -> OAuthAttemptView:
    return OAuthAttemptView(
        id=attempt.id,
        status=attempt.status,
        expires_at=attempt.expires_at,
        error_code=attempt.error_code,
        authorization_url=url,
    )


async def start(
    request: Request, db: AsyncSession, actor: NativeActor, service_id: UUID
) -> OAuthAttemptView:
    row = await lock_service(db, actor, service_id)
    if row.auth_mode != "oauth" or not row.oauth:
        fail(409, "oauth_not_supported", "此连接器不使用个人 OAuth")
    await resolve(row.oauth["authorization_url"], provider(request).settings)
    await cancel_pending(db, row.id, actor.member.id)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    attempt = NativeOAuthAttempt(
        state_hash=digest(state),
        device_id=actor.device.id,
        member_id=actor.member.id,
        service_id=row.id,
        version=row.version,
        verifier=provider(request).seal({"verifier": verifier}),
        expires_at=now() + timedelta(minutes=10),
        status="pending",
    )
    db.add(attempt)
    await db.flush()
    url = (
        row.oauth["authorization_url"]
        + "?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": row.oauth["client_id"],
                "redirect_uri": callback_url(request),
                "scope": row.oauth.get("scopes", ""),
                "state": state,
                "code_challenge": pkce(verifier),
                "code_challenge_method": "S256",
            }
        )
    )
    await db.commit()
    return view(attempt, url)


async def own_attempt(db: AsyncSession, actor: NativeActor, attempt_id: UUID) -> NativeOAuthAttempt:
    attempt = await db.scalar(
        select(NativeOAuthAttempt)
        .where(NativeOAuthAttempt.id == attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not attempt or attempt.device_id != actor.device.id or attempt.member_id != actor.member.id:
        fail(404, "oauth_attempt_not_found", "找不到本设备的授权尝试")
    if attempt.status in ACTIVE and attempt.expires_at <= now():
        attempt.status, attempt.error_code = "expired", "oauth_expired"
        attempt.verifier = attempt.pending_tokens = None
    return attempt


async def callback(request: Request, db: AsyncSession, state: str, code: str, error: str) -> None:
    # This browser endpoint deliberately ignores Web cookies; state + PKCE binds the attempt.
    attempt = await db.scalar(
        select(NativeOAuthAttempt)
        .where(NativeOAuthAttempt.state_hash == digest(state))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not attempt or attempt.status != "pending" or attempt.expires_at <= now():
        fail(400, "oauth_attempt_inactive", "授权已失效，请返回桌面重新发起")
    row = await db.get(McpService, attempt.service_id)
    if error or not code or not row or not row.oauth or row.version != attempt.version:
        attempt.status, attempt.error_code = "failed", "oauth_denied_or_changed"
        attempt.verifier = None
        await db.commit()
        return
    config = dict(row.oauth)
    verifier = provider(request).unseal(attempt.verifier or "")["verifier"]
    attempt.status, attempt.verifier = "exchanging", None
    attempt_id = attempt.id
    await db.commit()  # Cancellation must remain possible while the upstream is slow.
    sealed, failure = None, None
    try:
        tokens = await credentials.token_request(
            request,
            config["token_url"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": config["client_id"],
                "redirect_uri": callback_url(request),
                "code_verifier": verifier,
            },
        )
        sealed = provider(request).seal(tokens)
    except Exception:
        failure = "oauth_exchange_failed"
    attempt = await db.scalar(
        select(NativeOAuthAttempt)
        .where(NativeOAuthAttempt.id == attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not attempt or attempt.status != "exchanging":
        return
    if attempt.expires_at <= now():
        attempt.status, attempt.error_code = "expired", "oauth_expired"
    elif failure:
        attempt.status, attempt.error_code = "failed", failure
    else:
        attempt.status, attempt.pending_tokens = "awaiting_confirmation", sealed
    await db.commit()


async def complete(
    request: Request, db: AsyncSession, actor: NativeActor, attempt_id: UUID
) -> OAuthAttemptView:
    # Read identity first, then serialize attachment with disconnect/new attempt/config changes.
    initial = await db.get(NativeOAuthAttempt, attempt_id)
    if not initial or initial.device_id != actor.device.id or initial.member_id != actor.member.id:
        fail(404, "oauth_attempt_not_found", "找不到本设备的授权尝试")
    row = await lock_service(db, actor, initial.service_id)
    attempt = await own_attempt(db, actor, attempt_id)
    if attempt.status == "completed":
        return view(attempt)
    if row.version != attempt.version or row.auth_mode != "oauth":
        attempt.status, attempt.error_code = "failed", "connector_changed"
        attempt.pending_tokens = None
    elif attempt.status == "awaiting_confirmation" and attempt.pending_tokens:
        await credentials.store(
            request, db, row, actor, provider(request).unseal(attempt.pending_tokens)
        )
        attempt.status, attempt.pending_tokens = "completed", None
        record(db, actor, "mcp.oauth", row.id, row.name)
    elif attempt.status in ACTIVE:
        fail(409, "oauth_not_ready", "浏览器授权尚未完成，请继续查询状态")
    await db.commit()
    return view(attempt)
