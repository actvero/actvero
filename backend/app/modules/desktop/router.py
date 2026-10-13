import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import httpx2
from authlib.common.errors import AuthlibBaseError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from joserfc.errors import JoseError
from sqlalchemy import select, update

from app.modules.account.service import own_access
from app.modules.auth.identity import resolve_identity
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, address_key, digest, limit, now, provider
from app.modules.desktop import service
from app.modules.desktop.errors import fail
from app.modules.desktop.models import DesktopLogin, DeviceSession, DeviceToken
from app.modules.desktop.schemas import (
    DesktopBootstrap,
    DesktopBranding,
    DesktopCapabilities,
    DesktopErrorResponse,
    DesktopMe,
    DesktopMetadata,
    DesktopTokens,
    DesktopWorkspace,
    DeviceList,
    ExchangeLogin,
    LoginAttempt,
    LoginProof,
    LogoutSession,
    ModuleState,
    RefreshAcknowledgement,
    RefreshSession,
    StartLogin,
)
from app.modules.desktop.session_policy import initialize
from app.modules.members.models import Membership
from app.modules.members.service import membership_state
from app.modules.platform.branding import DEFAULT_PLATFORM_NAME, logo_url, public_branding
from app.modules.tenants.models import Installation, Tenant
from app.modules.users.models import User

ERRORS: dict[int | str, dict[str, Any]] = {
    status: {"model": DesktopErrorResponse, "description": description}
    for status, description in {
        400: "请求不合法；检查 error.code 和 request_id",
        401: ("凭据/设备会话无效或过期；access_expired 可受控续期，其他错误按接入说明处理"),
        403: "组织成员资格、客户端或权限范围不允许此操作",
        404: "本人设备或头像不存在",
        409: "登录已消费或续期凭据已轮换；不要换 request_id 盲目重试",
        422: "字段校验失败或不支持当前契约版本",
        429: "请求过于频繁，请降低重试频率",
        503: "身份服务暂不可用；保留本地会话，登录兑换失败需重新发起登录",
    }.items()
}
# Declare the existing header in OpenAPI. Actual validation remains desktop_actor.
desktop_access = HTTPBearer(
    scheme_name="DesktopAccess",
    description=(
        "桌面登录/续期返回的 access_token（desktop:"
        "self）。不是 Web Cookie、Keycloak Tok"
        "en 或 MCP 凭据。"
    ),
    auto_error=False,
)
BEARER = [Depends(desktop_access)]
router = APIRouter(
    prefix="/api/v1/desktop",
    tags=["desktop"],
    responses=ERRORS,
    dependencies=[Depends(service.native_request)],
)
web_router = APIRouter(prefix="/api/v1/account/devices", tags=["account"])


@router.get(
    "/metadata",
    summary="获取桌面接入配置",
    description=(
        "无需登录。DSH 启动时读取 issuer、公共 client_"
        "id、回调要求及有效期，客户端不要硬编码这些配置。"
    ),
    response_model=DesktopMetadata,
)
async def metadata(request: Request, db: DB) -> DesktopMetadata | Response:
    settings = provider(request).settings
    install = await db.get(Installation, 1)
    if install is None:
        fail(503, "installation_unavailable", "数据库尚未完成迁移")
    app_origin = urlsplit(settings.app_url)
    identity_origin = urlsplit(settings.oidc_issuer)
    result = DesktopMetadata(
        instance_id=install.instance_id,
        branding=DesktopBranding(
            name=install.platform_name or DEFAULT_PLATFORM_NAME,
            logo_url=logo_url(settings.app_url, install),
            revision=install.branding_revision,
            assets=dict(public_branding(settings.app_url, install).assets),
            favicon_url=public_branding(settings.app_url, install).favicon_url,
            apple_icon_url=public_branding(settings.app_url, install).apple_icon_url,
        ),
        capabilities=DesktopCapabilities(
            same_origin_identity=1
            if (app_origin.scheme, app_origin.netloc)
            == (identity_origin.scheme, identity_origin.netloc)
            else None
        ),
        issuer=settings.oidc_issuer,
        discovery_url=settings.oidc_issuer + "/.well-known/openid-configuration",
        client_id=settings.desktop_client_id,
        api_base=settings.app_url + "/api/v1",
        access_seconds=settings.desktop_access_seconds,
        session_hours=settings.desktop_session_hours,
        idle_minutes=settings.desktop_idle_minutes,
        retry_seconds=settings.desktop_retry_seconds,
        session_policy=settings.desktop_session_policy,
        recovery_days=settings.desktop_recovery_days,
        reauthentication_days=settings.desktop_reauthentication_days,
        unconfirmed_days=settings.desktop_unconfirmed_days,
    )

    body = result.model_dump(mode="json")
    # Preserve all pre-existing fields, including nullable policy values. Only optional
    # new projections are omitted when unavailable; old clients retain their shape.
    if body["branding"]["logo_url"] is None:
        body["branding"].pop("logo_url")
    if body["capabilities"]["same_origin_identity"] is None:
        body["capabilities"].pop("same_origin_identity")
    etag = '"' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=0, must-revalidate"}
    candidates = [
        value.strip().removeprefix("W/")
        for value in request.headers.get("if-none-match", "").split(",")
    ]
    if etag in candidates or "*" in candidates:
        return Response(status_code=304, headers=headers)
    return JSONResponse(body, headers=headers)


@router.post(
    "/login/start",
    summary="发起桌面登录",
    description=(
        "无需已有访问令牌。主进程先监听本机回调并生成 PKCE S256"
        "，再提交设备信息；用系统浏览器打开返回的 authorizati"
        "on_url。不要用内嵌登录 WebView。"
    ),
    response_model=LoginAttempt,
)
async def start(payload: StartLogin, request: Request, db: DB) -> LoginAttempt:
    await limit(db, address_key(request, "desktop-login"), 30, 300)
    state, nonce = (secrets.token_urlsafe(32) for _ in range(2))
    url = await service.native(request).authorization(
        payload.redirect_uri, state, nonce, payload.code_challenge, payload.reauthenticate
    )
    attempt = DesktopLogin(
        state_hash=digest(state),
        nonce=nonce,
        challenge=payload.code_challenge,
        redirect_uri=payload.redirect_uri,
        name=payload.device_name,
        os=payload.os,
        app_version=payload.app_version,
        expires_at=now() + timedelta(seconds=provider(request).settings.desktop_login_seconds),
    )
    db.add(attempt)
    await db.commit()
    return LoginAttempt(
        attempt_id=attempt.id,
        authorization_url=url,
        state=state,
        issuer=provider(request).settings.oidc_issuer,
        expires_at=attempt.expires_at,
    )


async def cached_tokens(
    request: Request, db: DB, sealed: str, *, allow_expired_access: bool = False
) -> DesktopTokens:
    result = DesktopTokens.model_validate(provider(request).unseal(sealed))
    access = await db.get(DeviceToken, digest(result.access_token))
    if not access or (access.expires_at <= now() and not allow_expired_access):
        fail(409, "retry_expired", "重试窗口已结束，请重新登录")
    result.expires_in = max(0, int((access.expires_at - now()).total_seconds()))
    result.server_time = now()
    return result


@router.post(
    "/login/exchange",
    summary="兑换桌面登录结果",
    description=(
        "主进程校验回调 state/iss 后提交一次性 code 和原"
        " verifier，取得独立设备会话。相同完整证明仅在短时重试窗"
        "口内幂等；不要记录请求体。"
    ),
    response_model=DesktopTokens,
)
async def exchange(payload: ExchangeLogin, request: Request, db: DB) -> DesktopTokens:
    await limit(db, address_key(request, "desktop-exchange"), 60, 300)
    if payload.issuer != provider(request).settings.oidc_issuer:
        fail(401, "invalid_login", "登录来源与当前平台不一致")
    attempt = await service.login_proof(db, payload)
    if attempt.cancelled:
        fail(401, "login_cancelled", "登录已取消，请重新发起")
    if attempt.consumed:
        session = await db.scalar(
            select(DeviceSession)
            .where(DeviceSession.id == attempt.session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if session:
            await service.check_device(request, db, session)
        if (
            session
            and attempt.code_hash == digest(payload.code.get_secret_value())
            and attempt.response
            and attempt.response_until
            and attempt.response_until > now()
        ):
            result = await cached_tokens(request, db, attempt.response)
            initial_refresh = await db.get(DeviceToken, digest(result.refresh_token))
            if not initial_refresh or initial_refresh.used_at:
                fail(409, "login_consumed", "登录凭据已续期，请使用已保存的新凭据")
            await db.commit()
            return result
        fail(409, "login_consumed", "此登录结果已使用，请重新发起")
    if attempt.expires_at <= now():
        fail(401, "login_expired", "登录尝试已过期，请重新发起")
    # Hold the attempt lock through exchange; concurrent callback/cancel must serialize.
    attempt.consumed = True
    try:
        claims = await service.native(request).exchange(
            payload.code.get_secret_value(),
            payload.code_verifier.get_secret_value(),
            attempt.nonce,
            attempt.redirect_uri,
        )
        authenticated_at = datetime.fromtimestamp(claims["auth_time"], UTC)
        await service.native(request).account_valid(str(claims["sub"]), authenticated_at)
    except (httpx.HTTPError, httpx2.HTTPError):
        await db.commit()  # An uncertain code exchange must never be retried as a fresh login.
        fail(503, "identity_unavailable", "身份服务暂不可用，请重新发起登录")
    except (AuthlibBaseError, JoseError, HTTPException, ValueError, KeyError, TypeError):
        await db.commit()
        fail(401, "invalid_login", "登录验证失败，请重新发起")
    identity, _ = await resolve_identity(db, provider(request).settings.oidc_issuer, claims)
    stamp = now()
    session = DeviceSession(
        identity_id=identity.id,
        client_id=provider(request).settings.desktop_client_id,
        scope="desktop:self",
        name=attempt.name,
        os=attempt.os,
        app_version=attempt.app_version,
        authenticated_at=authenticated_at,
        created_at=stamp,
        last_active_at=stamp,
        expires_at=stamp + timedelta(hours=provider(request).settings.desktop_session_hours),
        idle_expires_at=stamp + timedelta(minutes=provider(request).settings.desktop_idle_minutes),
    )
    initialize(session, provider(request).settings, stamp)
    db.add(session)
    await db.flush()
    result = await service.issue_tokens(request, db, session)
    await service.audit_device(
        db, session, "desktop.login", platform_edition=provider(request).settings.platform_edition
    )
    attempt.session_id = session.id
    attempt.code_hash = digest(payload.code.get_secret_value())
    attempt.response = provider(request).seal(result.model_dump(mode="json"))
    attempt.response_until = stamp + timedelta(
        seconds=provider(request).settings.desktop_retry_seconds
    )
    await db.commit()
    return result


@router.post(
    "/login/cancel",
    summary="取消桌面登录",
    description=(
        "使用原 attempt_id、state、verifier 取消"
        "当前尝试。若已兑换，也会撤销这次登录产生的设备会话，避免迟到回调"
        "重新登录。"
    ),
    response_model=Message,
)
async def cancel(payload: LoginProof, request: Request, db: DB) -> Message:
    await limit(db, address_key(request, "desktop-cancel"), 60, 300)
    attempt = await service.login_proof(db, payload)
    attempt.cancelled = True
    attempt.response = None
    if attempt.session_id:
        session = await db.scalar(
            select(DeviceSession).where(DeviceSession.id == attempt.session_id).with_for_update()
        )
        if session and not session.revoked_at:
            session.revoked_at = now()
            await service.audit_device(
                db,
                session,
                "desktop.cancelled",
                platform_edition=provider(request).settings.platform_edition,
            )
    await db.commit()
    return Message(message="已取消桌面登录")


@router.post(
    "/refresh",
    summary="续期并轮换桌面凭据",
    description=(
        "使用请求体 refresh_token，不使用 Bearer a"
        "ccess。主进程串行续期，先保存 request_id；丢包重"
        "试必须使用同一旧 refresh_token 和同一 reque"
        "st_id。成功后原子替换两种凭据。"
    ),
    response_model=DesktopTokens,
)
async def refresh(payload: RefreshSession, request: Request, db: DB) -> DesktopTokens:
    await limit(db, address_key(request, "desktop-refresh"), 120, 300)
    token, session = await service.token_session(
        db, payload.refresh_token.get_secret_value(), "refresh"
    )
    await service.check_device(request, db, session)
    if token.expires_at <= now():
        fail(401, "session_expired", "桌面登录已过期，请重新登录")
    if token.used_at:
        successor = (
            await db.get(DeviceToken, token.successor_hash) if token.successor_hash else None
        )
        if (
            token.request_id == payload.request_id
            and token.response
            and token.response_until
            and token.response_until > now()
            and successor
            and not successor.used_at
        ):
            result = await cached_tokens(request, db, token.response, allow_expired_access=True)
            await db.commit()
            return result
        if token.request_id == payload.request_id and token.acknowledged_at is None:
            fail(409, "refresh_recovery_expired", "未确认的续期结果已无法恢复，请重新登录")
        fail(409, "refresh_replayed", "续期凭据已轮换，请使用已保存的新凭据或重新登录")
    await db.execute(
        update(DeviceToken)
        .where(
            DeviceToken.session_id == session.id,
            DeviceToken.successor_hash == token.token_hash,
        )
        .values(response=None, acknowledged_at=now())
    )
    result = await service.issue_tokens(request, db, session)
    token.used_at = now()
    token.request_id = payload.request_id
    token.successor_hash = digest(result.refresh_token)
    token.response_until = min(
        session.expires_at,
        now()
        + (
            timedelta(days=provider(request).settings.desktop_unconfirmed_days)
            if payload.recovery_version == 2
            else timedelta(seconds=provider(request).settings.desktop_retry_seconds)
        ),
    )
    result.acknowledgement_required = payload.recovery_version == 2
    result.refresh_request_id = payload.request_id
    result.recovery_until = token.response_until
    token.response = provider(request).seal(result.model_dump(mode="json"))
    await db.commit()
    return result


@router.post("/refresh/acknowledge", response_model=Message)
async def acknowledge(payload: RefreshAcknowledgement, request: Request, db: DB) -> Message:
    token, session = await service.token_session(
        db, payload.refresh_token.get_secret_value(), "refresh"
    )
    await service.check_device(request, db, session)
    parent = await db.scalar(
        select(DeviceToken).where(
            DeviceToken.session_id == session.id,
            DeviceToken.successor_hash == token.token_hash,
            DeviceToken.request_id == payload.request_id,
        )
    )
    if parent is None:
        fail(409, "refresh_acknowledgement_mismatch", "续期确认不匹配，请检查已保存的请求编号")
    parent.response = None
    parent.acknowledged_at = parent.acknowledged_at or now()
    await db.commit()
    return Message(message="续期凭据已确认保存")


@router.post("/organization", response_model=DesktopMe, dependencies=BEARER)
async def select_organization(payload: DesktopWorkspace, request: Request, db: DB) -> DesktopMe:
    actor = await service.desktop_actor(request, db)
    tenant = await db.get(Tenant, payload.tenant_id)
    member = await db.scalar(
        select(Membership)
        .where(
            Membership.tenant_id == payload.tenant_id,
            Membership.user_id == actor.user.id,
            Membership.source != "platform",
        )
        .execution_options(populate_existing=True)
    )
    reason = membership_state(tenant, member, actor.session.authenticated_at)
    if reason:
        fail(
            401 if reason == "reauthentication_required" else 403,
            reason,
            "当前组织资格不可用，请重新选择或验证身份",
        )
    actor.session.tenant_id = payload.tenant_id
    result = await service.me(request, db, actor)
    await db.commit()
    return result


@router.post(
    "/logout",
    summary="退出当前桌面设备",
    description=(
        "使用请求体 refresh_token，幂等撤销所属设备。已轮换"
        "或过期的 refresh 仅可用于退出；不退出其他设备或 Web"
        "。网络失败不能宣称服务端已退出。"
    ),
    response_model=Message,
)
async def logout(payload: LogoutSession, request: Request, db: DB) -> Message:
    # A rotated/expired refresh token still permits ending its own session, never access.
    _, session = await service.token_session(
        db, payload.refresh_token.get_secret_value(), "refresh"
    )
    if not session.revoked_at:
        session.revoked_at = now()
        await service.audit_device(
            db,
            session,
            "desktop.logout",
            platform_edition=provider(request).settings.platform_edition,
        )
    await db.commit()
    return Message(message="已退出此设备")


@router.get(
    "/me",
    summary="获取桌面本人资料",
    description=(
        "认证：Authorization: Bearer <access"
        "_token>。返回本人资料、组织选择及成员状态、当前设备与账号管"
        "理地址。organization=null 表示未加入组织；有账"
        "号不等于有 MCP 使用权限。"
    ),
    dependencies=BEARER,
    response_model=DesktopMe,
)
async def me(request: Request, db: DB) -> DesktopMe:
    actor = await service.desktop_actor(request, db)
    result = await service.me(request, db, actor)
    await db.commit()
    return result


@router.get(
    "/bootstrap",
    summary="获取桌面初始化状态",
    description=(
        "桌面 Bearer 认证，需有效成员。tenant_id 取自 me。MCP、Skills 与模型网关可用；"
        "模型调用仍需授权、计价与额度策略就绪。"
    ),
    dependencies=BEARER,
    response_model=DesktopBootstrap,
)
async def bootstrap(request: Request, db: DB, tenant_id: UUID) -> DesktopBootstrap:
    actor = await service.desktop_actor(request, db)
    await service.require_organization(
        db,
        actor,
        tenant_id,
        platform_edition=provider(request).settings.platform_edition,
    )
    own = await service.me(request, db, actor)
    result = DesktopBootstrap(
        **own.model_dump(),
        modules=[
            ModuleState(name=n, status="available", reason=None)
            if n in {"mcp", "models", "skills", "experts"}
            else ModuleState(name=n)
            for n in ("models", "mcp", "skills", "experts")
        ],
    )
    await db.commit()
    return result


@router.get(
    "/avatar",
    summary="获取本人头像",
    description=(
        "认证：桌面 Bearer。主进程携带请求头读取 image/webp；没有头像返回 404。令牌不能放进 URL。"
    ),
    dependencies=BEARER,
    response_class=Response,
    responses={
        200: {"content": {"image/webp": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def avatar(request: Request, db: DB) -> Response:
    actor = await service.desktop_actor(request, db)
    data = await db.scalar(select(User.avatar_data).where(User.id == actor.user.id))
    if data is None:
        fail(404, "avatar_not_found", "尚未设置头像")
    await db.commit()
    return Response(data, media_type="image/webp")


@router.get(
    "/devices",
    summary="列出本人的登录设备",
    description=(
        "认证：桌面 Bearer。返回本人全部设备记录，包括已过期/撤销"
        "记录；current 标记当前设备。不返回任何凭据。"
    ),
    dependencies=BEARER,
    response_model=DeviceList,
)
async def list_devices(request: Request, db: DB) -> DeviceList:
    actor = await service.desktop_actor(request, db)
    result = await service.devices(db, actor.user.id, actor.session.id, provider(request).settings)
    await db.commit()
    return result


@router.delete(
    "/devices/{session_id}",
    summary="撤销本人的指定设备",
    description=(
        "认证：桌面 Bearer。session_id 来自设备列表，只"
        "能撤销本人设备；撤销当前设备后停止业务请求并清理本地凭据。"
    ),
    dependencies=BEARER,
    response_model=Message,
)
async def revoke_device(session_id: UUID, request: Request, db: DB) -> Message:
    actor = await service.desktop_actor(request, db)
    user_id, caller_id = actor.user.id, actor.session.id
    # Acquire both device locks in stable order (two devices may revoke one another).
    await db.commit()
    await db.scalars(
        select(DeviceSession)
        .where(DeviceSession.id.in_([session_id, caller_id]))
        .order_by(DeviceSession.id)
        .with_for_update()
    )
    await service.desktop_actor(request, db)
    await service.revoke(
        db,
        user_id,
        session_id,
        platform_edition=provider(request).settings.platform_edition,
    )
    await db.commit()
    return Message(message="已退出此设备")


@web_router.get(
    "",
    response_model=DeviceList,
    summary="网页：列出本人桌面设备",
    description="需要 Web 登录 Cookie；不接受桌面 Bearer。",
)
async def web_devices(request: Request, db: DB) -> DeviceList:
    actor = await own_access(request, db)
    result = await service.devices(db, actor.user.id, settings=provider(request).settings)
    await db.commit()
    return result


@web_router.delete(
    "/{session_id}",
    response_model=Message,
    summary="网页：撤销本人桌面设备",
    description=("需要 Web 登录 Cookie、合法 Origin 和 X-CSRF-Token；只能撤销本人设备。"),
)
async def web_revoke(session_id: UUID, request: Request, db: DB, _: Mutation) -> Message:
    actor = await own_access(request, db)
    await service.revoke(
        db,
        actor.user.id,
        session_id,
        platform_edition=provider(request).settings.platform_edition,
    )
    await db.commit()
    return Message(message="已退出此设备")
