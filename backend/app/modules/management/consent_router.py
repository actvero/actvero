"""Browser approval is separate from native CLI credentials and PKCE exchange."""

import secrets
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.modules.auth.schemas import UserView
from app.modules.auth.service import (
    DB,
    authenticate,
    digest,
    mutation_session,
    now,
    provider,
    session_for,
)
from app.modules.desktop.errors import fail
from app.modules.management import schemas as s
from app.modules.management.models import ManagementLogin, ManagementSession
from app.modules.management.service import ManagementActor, native, organization
from app.modules.management.settings import require_enabled
from app.modules.members.models import Membership
from app.modules.tenants.models import Tenant

router = APIRouter(prefix="/api/v1/cli-authorization", tags=["management-consent"])


async def context(
    payload: s.CliConsentProof,
    request: Request,
    db: DB,
) -> tuple[ManagementLogin, ManagementActor]:
    await require_enabled(request, db)
    await mutation_session(request, db)
    _, identity, user = await authenticate(request, db)
    browser = await session_for(request, db, lock=True)
    if not browser or browser.identity_id != identity.id or not browser.authenticated_at:
        fail(401, "login_required", "登录账号已变化，请刷新后重试")
    if identity.issuer != provider(request).settings.oidc_issuer:
        fail(401, "invalid_identity", "登录身份已失效")
    attempt = await db.scalar(
        select(ManagementLogin)
        .where(ManagementLogin.id == payload.attempt_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not attempt or not secrets.compare_digest(
        attempt.state_hash, digest(payload.state.get_secret_value())
    ):
        fail(404, "invalid_login", "授权请求无效")
    if (
        attempt.authorization_version != 2
        or attempt.cancelled
        or attempt.consumed
        or attempt.approved_at
    ):
        fail(409, "authorization_finished", "此授权请求已结束，请返回 CLI 重新发起")
    if attempt.expires_at <= now():
        fail(410, "login_expired", "授权请求已过期，请返回 CLI 重新发起")
    # This transient actor only checks live memberships; it is never issued as a credential.
    session = ManagementSession(
        id=uuid4(),
        identity_id=identity.id,
        scope="management:read management:write",
        authorized_org_ids=None,
        authenticated_at=browser.authenticated_at,
    )
    return attempt, ManagementActor(session, identity, user)


@router.post("/context", response_model=s.CliConsentView)
async def view(payload: s.CliConsentProof, request: Request, db: DB) -> s.CliConsentView:
    attempt, actor = await context(payload, request, db)
    ids = (
        await db.scalars(
            select(Tenant.id)
            .join(Membership)
            .where(Membership.user_id == actor.user.id)
            .order_by(Tenant.name, Tenant.id)
        )
    ).all()
    organizations = []
    for org_id in ids:
        try:
            _, item = await organization(request, db, actor, org_id, require_admin=True)
            organizations.append(item)
        except HTTPException as error:
            if error.status_code not in {401, 403}:
                raise
    result = s.CliConsentView(
        device_name=attempt.name,
        expires_at=attempt.expires_at,
        user=UserView.model_validate(actor.user),
        organizations=organizations,
    )
    await db.commit()
    return result


@router.post("/decision", response_model=s.CliConsentResult)
async def decide(payload: s.CliConsentDecision, request: Request, db: DB) -> s.CliConsentResult:
    attempt, actor = await context(payload, request, db)
    state = payload.state.get_secret_value()
    if not payload.approve:
        attempt.cancelled = True
        url = (
            attempt.redirect_uri
            + "?"
            + urlencode(
                {
                    "state": state,
                    "iss": provider(request).settings.oidc_issuer,
                    "error": "access_denied",
                }
            )
        )
    else:
        ids = sorted(set(payload.org_ids))
        if not ids or len(ids) != len(payload.org_ids):
            fail(422, "invalid_organizations", "请选择至少一个组织，且不能重复选择")
        actor.session.scope = payload.scope
        for org_id in ids:
            await organization(
                request,
                db,
                actor,
                org_id,
                require_admin=True,
                write="management:write" in payload.scope.split(),
            )
        url = await native(request).authorization(
            attempt.redirect_uri,
            state,
            attempt.nonce,
            attempt.challenge,
            attempt.reauthenticate,
        )
        attempt.scope = payload.scope
        attempt.authorized_org_ids = [str(value) for value in ids]
        attempt.approved_identity_id = actor.identity.id
        attempt.approved_at = now()
    await db.commit()
    return s.CliConsentResult(redirect_url=url)
