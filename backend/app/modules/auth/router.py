import logging
import secrets
from datetime import timedelta
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

import httpx
import httpx2
from authlib.common.errors import AuthlibBaseError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from sqlalchemy import select

from app.modules.auth.identity import resolve_identity
from app.modules.auth.models import OrganizationOpeningFlow, WebSession
from app.modules.auth.return_to import login_return_to
from app.modules.auth.schemas import (
    EnterpriseAccess,
    Message,
    PasswordAction,
    SessionView,
    UserView,
    WorkspaceSelection,
)
from app.modules.auth.service import (
    DB,
    address_key,
    authenticate,
    browser_session,
    digest,
    limit,
    mutation_session,
    now,
    provider,
    session_for,
    set_cookie,
)
from app.modules.auth.session_policy import deadline, initialize
from app.modules.members.models import Membership
from app.modules.platform.branding import logo_url
from app.modules.platform.mail_settings import effective_mail
from app.modules.platform.opening_flows import current_flow, return_path
from app.modules.tenants.models import Installation, PlatformOperator, Tenant
from app.modules.tenants.service import finish_initial_setup
from app.modules.users.models import LoginIdentity

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)
Browser = Annotated[WebSession, Depends(browser_session)]
Mutation = Annotated[WebSession, Depends(mutation_session)]


@router.get("/session", response_model=SessionView)
async def context(request: Request, response: Response, db: DB, browser: Browser) -> SessionView:
    settings = provider(request).settings
    install = await db.get(Installation, 1)
    setup_complete = bool(
        install
        and (
            install.tenant_id
            if settings.platform_edition == "community"
            else install.platform_operator_user_id
        )
    )
    result = SessionView(
        authenticated=False,
        csrf=browser.csrf,
        setup_complete=setup_complete,
        invitations_enabled=effective_mail(provider(request), install).invitations_enabled,
        invitation_hours=settings.invitation_hours,
        platform_edition=settings.platform_edition,
        registration_mode=install.registration_mode
        if install and settings.platform_edition == "saas"
        else "invite",
        platform_name=(install.platform_name if install and install.platform_name else "Actvero"),
        platform_logo_url=logo_url(settings.app_url, install) if install else None,
    )
    result.setup_account_created = bool(install and install.subject)
    if browser.identity_id:
        session, identity, user = await authenticate(request, db)
        # Authentication commits token rotation. Re-lock before saving workspace state:
        # a concurrent logout or account switch must not let this stale object write later.
        current = await session_for(request, db, lock=True)
        if current is None or current.identity_id != identity.id:
            raise HTTPException(401, "登录会话已变化，请刷新后重试")
        session = current
        result.authenticated = True
        result.session_policy = session.policy_mode
        result.session_expires_at = deadline(session, settings)
        result.reauthenticate_at = session.absolute_expires_at
        if session.policy_mode == "persistent":
            set_cookie(response, request, request.cookies[settings.session_cookie_name], session)
        result.user = UserView.model_validate(user)
        result.platform_operator = (
            await db.scalar(
                select(PlatformOperator.user_id).where(
                    PlatformOperator.user_id == user.id,
                    PlatformOperator.status == "active",
                )
            )
            is not None
        )
        memberships = (
            await db.execute(
                select(Membership, Tenant)
                .join(Tenant)
                .where(Membership.user_id == user.id)
                .order_by(Tenant.name, Tenant.id)
            )
        ).all()
        accesses = [
            EnterpriseAccess(
                tenant_id=tenant.id,
                name=tenant.name,
                role=member.role,
                status=member.status if tenant.active else "unavailable",
                needs_login=bool(
                    member.revoked_at
                    and (
                        not session.authenticated_at
                        or session.authenticated_at <= member.revoked_at
                    )
                ),
            )
            for member, tenant in memberships
            if member.status in {"active", "paused"}
        ]
        if result.platform_operator and settings.platform_edition == "saas":
            tenants = (await db.scalars(select(Tenant).order_by(Tenant.name, Tenant.id))).all()
            accesses = [
                EnterpriseAccess(
                    tenant_id=tenant.id,
                    name=tenant.name,
                    role="administrator",
                    status="active",
                    needs_login=False,
                )
                for tenant in tenants
            ]
        else:
            platform_ids = {
                member.tenant_id for member, _ in memberships if member.source == "platform"
            }
            accesses = [item for item in accesses if item.tenant_id not in platform_ids]
        result.organizations = accesses
        selected = next(
            (
                organization
                for organization in accesses
                if organization.tenant_id == session.tenant_id
            ),
            None,
        )
        # Platform operators start in the platform workspace. Other users are
        # placed in their first organization when no choice was saved.
        if selected is None and not result.platform_operator and accesses:
            selected = accesses[0]
            session.tenant_id = selected.tenant_id
            await db.commit()
        result.organization = selected
        result.account_url = settings.oidc_issuer + "/account/"
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.get("/login", response_class=RedirectResponse)
async def login(
    request: Request, db: DB, next: str = "/console", switch: bool = False, flow: UUID | None = None
) -> Response:
    next = login_return_to(next)
    await limit(db, address_key(request, "login"), 40, 300)
    response = RedirectResponse("/")
    session = await browser_session(request, response, db)
    flow_context = await current_flow(request, db)
    if flow_context:
        destination = return_path(flow_context)
        if next != destination.split("?")[0]:
            raise HTTPException(400, "登录返回地址与开通流程不一致")
        next = destination
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    url = await provider(request).authorization(
        state, nonce, verifier, switch or session.requires_reauth
    )
    session.login_state = digest(state)
    session.login_data = provider(request).seal(
        {"nonce": nonce, "verifier": verifier, "next": next}
    )
    session.login_expires_at = now() + timedelta(minutes=10)
    if flow_context:
        flow_context.login_state = session.login_state
        flow_context.login_expires_at = session.login_expires_at
    await db.commit()
    response.headers["location"] = url
    return response


@router.post("/password", response_model=PasswordAction)
async def password_action(request: Request, db: DB, _: Mutation) -> PasswordAction:
    from app.modules.account.service import own_access

    actor = await own_access(request, db)
    identity = await db.get(LoginIdentity, actor.session.identity_id)
    assert identity is not None
    await limit(db, "password:" + str(actor.user.id), 10, 300)
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    url = await provider(request).authorization(state, nonce, verifier, False, password=True)
    current = await session_for(request, db, lock=True)
    if not current or current.identity_id != identity.id:
        raise HTTPException(401, "登录已失效，请重新登录")
    current.login_state = digest(state)
    current.login_data = provider(request).seal(
        {
            "nonce": nonce,
            "verifier": verifier,
            "next": "/account?tab=security",
            "subject": identity.subject,
        }
    )
    current.login_expires_at = now() + timedelta(minutes=10)
    await db.commit()
    return PasswordAction(url=url)


@router.get("/callback", response_class=RedirectResponse)
async def callback(request: Request, db: DB) -> Response:
    state = request.query_params.get("state", "")
    session = await session_for(request, db, lock=True)
    if (
        not session
        or not session.login_state
        or not secrets.compare_digest(session.login_state, digest(state))
        or not session.login_data
        or not session.login_expires_at
        or session.login_expires_at <= now()
    ):
        # Only log rejection categories, never cookies, state, codes or tokens.
        reason = (
            "missing_session"
            if not session
            else "missing_attempt"
            if not session.login_state
            else "state_mismatch"
            if not secrets.compare_digest(session.login_state, digest(state))
            else "missing_login_data"
            if not session.login_data
            else "expired_attempt"
        )
        logger.warning(
            "OIDC callback rejected (%s; session_cookie_present=%s)",
            reason,
            bool(request.cookies.get(provider(request).settings.session_cookie_name)),
        )
        # A newer tab's login wins; the older tab can still return to its own task.
        flow_context = await db.scalar(
            select(OrganizationOpeningFlow).where(
                OrganizationOpeningFlow.session_id == (session.id if session else None),
                OrganizationOpeningFlow.login_state == digest(state),
                OrganizationOpeningFlow.login_expires_at > now(),
            )
        )
        destination = (
            return_path(flow_context) + "&login_error=callback"
            if flow_context
            else "/login?error=callback"
        )
        return RedirectResponse(destination, status_code=303)
    data = provider(request).unseal(session.login_data)

    def failure(reason: str) -> RedirectResponse:
        destination = (
            "/account?tab=security&password=" + ("cancelled" if reason == "cancelled" else "error")
            if data.get("subject")
            else "/login?"
            + urlencode(
                {"error": reason, **({"next": data["next"]} if data["next"] != "/" else {})}
            )
        )
        if data["next"].startswith(
            ("/organization-invite?flow=", "/organization-onboarding?flow=")
        ):
            destination = data["next"] + "&login_error=" + reason
        return RedirectResponse(destination, status_code=303)

    session.login_state = digest("consumed:" + state)
    session.login_data = None
    await db.commit()
    if request.query_params.get("error") or not request.query_params.get("code"):
        return failure("cancelled")
    if (
        request.query_params.get("iss", provider(request).settings.oidc_issuer)
        != provider(request).settings.oidc_issuer
    ):
        return failure("callback")
    try:
        tokens, claims = await provider(request).exchange(
            request.query_params["code"], data["verifier"], data["nonce"]
        )
        subject = str(claims["sub"])
        if data.get("subject") and subject != data["subject"]:
            raise HTTPException(403, "修改密码的账号与当前账号不一致")
        await provider(request).inspect(tokens, subject)
    except (
        AuthlibBaseError,
        JoseError,
        httpx.HTTPError,
        httpx2.HTTPError,
        HTTPException,
        ValueError,
        KeyError,
    ) as error:
        # Never log authorization codes, tokens, exception URLs or upstream bodies.
        logger.warning("OIDC callback validation failed (%s)", type(error).__name__)
        return failure("callback")
    identity, user = await resolve_identity(db, provider(request).settings.oidc_issuer, claims)
    # Re-lock after remote I/O: logout or a newer login must win over this result.
    current = await session_for(request, db, lock=True)
    if current is None or current.login_state != digest("consumed:" + state):
        await db.rollback()
        return failure("callback")
    raw = secrets.token_urlsafe(32)
    current.token_hash = digest(raw)
    current.csrf = secrets.token_urlsafe(32)
    if current.identity_id != identity.id:
        current.tenant_id = None
    current.identity_id = identity.id
    current.login_state = None
    current.tokens = provider(request).seal(tokens)
    current.requires_reauth = False
    current.authenticated_at = now()
    initialize(current, provider(request).settings, current.authenticated_at)
    await finish_initial_setup(
        db,
        identity,
        user,
        platform_edition=provider(request).settings.platform_edition,
    )
    await db.commit()
    destination = "/console" if data["next"] in ("/", "/setup") else data["next"]
    if data.get("subject") and request.query_params.get("kc_action_status") == "cancelled":
        destination = "/account?tab=security&password=cancelled"
    response = RedirectResponse(destination, status_code=303)
    set_cookie(response, request, raw, current)
    return response


@router.post("/workspace", response_model=Message)
async def select_workspace(
    payload: WorkspaceSelection, request: Request, db: DB, session: Mutation
) -> Message:
    _, _, user = await authenticate(request, db)
    settings = provider(request).settings
    if payload.tenant_id is None:
        operator = await db.scalar(
            select(PlatformOperator.user_id).where(
                PlatformOperator.user_id == user.id,
                PlatformOperator.status == "active",
            )
        )
        if operator is None:
            raise HTTPException(403, "你没有平台运营权限")
    else:
        operator = (
            await db.scalar(
                select(PlatformOperator).where(
                    PlatformOperator.user_id == user.id, PlatformOperator.status == "active"
                )
            )
            if settings.platform_edition == "saas"
            else None
        )
        if operator:
            from app.modules.platform.opening_service import audit, operator_member

            tenant = await db.scalar(
                select(Tenant).where(Tenant.id == payload.tenant_id).with_for_update()
            )
            if not tenant:
                raise HTTPException(404, "组织不存在")
            await operator_member(db, tenant.id, user.id)
            audit(db, user, tenant, "platform.organization.entered")
            session.tenant_id = tenant.id
            await db.commit()
            return Message(message="已进入组织管理")
        membership = await db.scalar(
            select(Membership).where(
                Membership.tenant_id == payload.tenant_id,
                Membership.user_id == user.id,
                Membership.status == "active",
            )
        )
        if membership is None or membership.source == "platform":
            raise HTTPException(403, "你没有此组织的访问权限")
        if settings.platform_edition == "community":
            install = await db.get(Installation, 1)
            if not install or install.tenant_id != payload.tenant_id:
                raise HTTPException(403, "你没有此组织的访问权限")
    session.tenant_id = payload.tenant_id
    await db.commit()
    return Message(message="工作空间已切换")


@router.post("/logout", response_model=Message)
async def logout(request: Request, response: Response, db: DB, session: Mutation) -> Message:
    current = await session_for(request, db, lock=True)
    if current:
        await db.delete(current)
    # Keep only an anonymous, rotated browser session to remember explicit logout.
    # OIDC may reuse SSO for ordinary visits, but logout must require fresh login.
    raw = secrets.token_urlsafe(32)
    db.add(
        WebSession(
            token_hash=digest(raw),
            csrf=secrets.token_urlsafe(32),
            requires_reauth=True,
            expires_at=now() + timedelta(hours=provider(request).settings.session_hours),
        )
    )
    await db.commit()
    set_cookie(response, request, raw)
    return Message(message="已退出当前应用")
