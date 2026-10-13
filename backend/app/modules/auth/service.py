import hashlib
import math
import secrets
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast

import httpx
import httpx2
from authlib.integrations.base_client.errors import OAuthError
from cryptography.fernet import InvalidToken
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Database
from app.modules.auth.failures import IdentityUnavailable
from app.modules.auth.models import RateLimit, WebSession
from app.modules.auth.oidc import IdentityProvider
from app.modules.auth.session_policy import deadline, renew
from app.modules.users.models import LoginIdentity, User

COOKIE = "actvero_community_session"


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def database(request: Request) -> AsyncIterator[AsyncSession]:
    db = cast(Database, request.app.state.database)
    if db.engine is None:
        raise HTTPException(503, "数据库尚未配置")
    async with db.sessions() as session:
        yield session


DB = Annotated[AsyncSession, Depends(database)]


def provider(request: Request) -> IdentityProvider:
    return cast(IdentityProvider, request.app.state.identity_provider)


def set_cookie(
    response: Response, request: Request, raw: str, session: WebSession | None = None
) -> None:
    settings = provider(request).settings
    response.set_cookie(
        settings.session_cookie_name,
        raw,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        max_age=(
            max(0, math.ceil((deadline(session, settings) - now()).total_seconds()))
            if session is not None
            else settings.session_hours * 3600
        ),
    )


def check_origin(request: Request) -> None:
    if request.headers.get("origin") != provider(request).settings.app_url:
        raise HTTPException(403, "请求来源无效，请从当前应用重试")


async def session_for(request: Request, db: AsyncSession, lock: bool = False) -> WebSession | None:
    raw = request.cookies.get(provider(request).settings.session_cookie_name, "")
    if not raw or len(raw) > 200:
        return None
    query = select(WebSession).where(
        WebSession.token_hash == digest(raw), WebSession.expires_at > now()
    )
    if lock:
        query = query.with_for_update()
    session = cast(
        WebSession | None, await db.scalar(query.execution_options(populate_existing=True))
    )
    if session is not None and deadline(session, provider(request).settings) <= now():
        return None
    return session


async def browser_session(request: Request, response: Response, db: DB) -> WebSession:
    session = await session_for(request, db)
    if session is None:
        old_raw = request.cookies.get(provider(request).settings.session_cookie_name, "")
        old = (
            await db.scalar(select(WebSession).where(WebSession.token_hash == digest(old_raw)))
            if old_raw and len(old_raw) <= 200
            else None
        )
        raw = secrets.token_urlsafe(32)
        session = WebSession(
            token_hash=digest(raw),
            csrf=secrets.token_urlsafe(32),
            requires_reauth=bool(old and (old.identity_id or old.requires_reauth)),
            expires_at=now() + timedelta(hours=provider(request).settings.session_hours),
        )
        db.add(session)
        await db.commit()
        set_cookie(response, request, raw)
    return session


async def mutation_session(request: Request, db: DB) -> WebSession:
    check_origin(request)
    session = await session_for(request, db)
    if session is None or not secrets.compare_digest(
        request.headers.get("x-csrf-token", ""), session.csrf
    ):
        raise HTTPException(403, "页面会话已变化，请刷新后重试")
    return session


async def authenticate(
    request: Request, db: AsyncSession
) -> tuple[WebSession, LoginIdentity, User]:
    if request.headers.get("authorization"):
        raise HTTPException(401, "后台接口仅接受网页登录会话")
    # Serialize refresh token rotation across tabs and processes.
    session = await session_for(request, db, lock=True)
    if session is None or session.identity_id is None or session.tokens is None:
        raise HTTPException(401, "请先登录")
    identity = await db.get(LoginIdentity, session.identity_id)
    if identity is None:
        raise HTTPException(401, "登录身份已失效")
    upstream = provider(request)
    try:
        tokens = upstream.unseal(session.tokens)
        if tokens.get("expires_at", 0) < time.time() + 30:
            tokens = await upstream.refresh(tokens)
            session.tokens = upstream.seal(tokens)
        await upstream.inspect(tokens, identity.subject)
    except OAuthError as error:
        if error.error not in {"invalid_grant", "invalid_token", "token_invalid"}:
            # invalid_client and unsupported responses require operator recovery,
            # not destruction of every user's stored session.
            await db.commit()
            raise IdentityUnavailable() from None
        session.requires_reauth = True
        session.identity_id = None
        session.tokens = None
        await db.commit()
        raise HTTPException(401, "登录已失效，请重新登录") from None
    except (httpx.HTTPError, httpx2.HTTPError) as error:
        # Refresh may have succeeded before introspection failed. Persist the
        # successor under the same lock so the next attempt doesn't replay the old token.
        await db.commit()
        raise IdentityUnavailable(error) from None
    except ValueError:
        await db.commit()
        raise IdentityUnavailable() from None
    except (KeyError, InvalidToken):
        session.requires_reauth = True
        session.identity_id = None
        session.tokens = None
        await db.commit()
        raise HTTPException(401, "登录已失效，请重新登录") from None
    except HTTPException as error:
        if error.status_code == 401:
            session.requires_reauth = True
            session.identity_id = None
            session.tokens = None
            await db.commit()
        elif session.tokens is not None:
            await db.commit()
        raise
    user = await db.get(User, identity.user_id)
    if user is None:
        raise HTTPException(401, "登录身份已失效")
    renew(session, upstream.settings, now())
    await db.commit()
    return session, identity, user


async def limit(db: AsyncSession, key: str, maximum: int, seconds: int) -> None:
    stamp = now()
    await db.execute(
        insert(RateLimit)
        .values(key=key, count=0, reset_at=stamp + timedelta(seconds=seconds))
        .on_conflict_do_nothing()
    )
    row = await db.scalar(select(RateLimit).where(RateLimit.key == key).with_for_update())
    assert row is not None
    if row.reset_at <= stamp:
        row.count = 0
        row.reset_at = stamp + timedelta(seconds=seconds)
    row.count += 1
    blocked = row.count > maximum
    await db.commit()
    if blocked:
        raise HTTPException(429, "操作过于频繁，请稍后重试", headers={"Retry-After": str(seconds)})


def address_key(request: Request, prefix: str) -> str:
    # Never trust arbitrary forwarded headers for security decisions.
    return prefix + ":" + digest(request.client.host if request.client else "unknown")
