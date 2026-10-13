import secrets
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.security import HTTPBearer
from sqlalchemy import func, literal, or_, select, union_all

from app.modules.access_keys import service
from app.modules.access_keys.models import AccessKey, AccessKeyPolicy
from app.modules.access_keys.schemas import (
    KeyAction,
    KeyCreate,
    KeyCreated,
    KeyPage,
    KeyPolicyView,
    KeyResourcePage,
    KeyReveal,
    KeySecret,
    KeyUsage,
    KeyUsagePage,
    KeyView,
)
from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, digest, limit, now, provider
from app.modules.desktop.errors import fail
from app.modules.llm.models import CatalogModel, ModelCall
from app.modules.mcp.models import McpActivity
from app.modules.members.models import Membership
from app.modules.members.service import Access, record
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1", tags=["access-keys"])
bearer = HTTPBearer(
    scheme_name="PersonalAccessKey",
    auto_error=False,
    description="个人中心创建的 avk_ 密钥。仅限显式开放的调用入口，不适用于后台或桌面会话接口。",
)


async def access(request: Request, db: DB, admin: bool = False, write: bool = False) -> Access:
    actor = await own_access(request, db, write=write)
    if admin and actor.member.role != "administrator":
        fail(403, "administrator_required", "仅管理员可以管理组织访问密钥")
    return actor


async def key_row(db: DB, actor: Access, key_id: UUID, admin: bool) -> AccessKey:
    row = await db.get(AccessKey, key_id, populate_existing=True)
    if (
        not row
        or row.deleted_at is not None
        or row.tenant_id != actor.tenant.id
        or (not admin and row.member_id != actor.member.id)
    ):
        fail(404, "key_not_found", "访问密钥不存在")
    return row


@router.get("/account/access-keys", response_model=KeyPage)
@router.get("/access-keys", response_model=KeyPage)
async def keys(
    request: Request, db: DB, page: int = Query(1, ge=1), q: str = Query("", max_length=100)
) -> KeyPage:
    admin = request.url.path == "/api/v1/access-keys"
    actor = await access(request, db, admin)
    query = (
        select(AccessKey, Membership, User.name)
        .join(Membership, Membership.id == AccessKey.member_id)
        .join(User, User.id == Membership.user_id)
        .where(AccessKey.tenant_id == actor.tenant.id, AccessKey.deleted_at.is_(None))
    )
    if not admin:
        query = query.where(AccessKey.member_id == actor.member.id)
    if q.strip():
        query = query.where(
            AccessKey.name.icontains(q.strip(), autoescape=True)
            | User.name.icontains(q.strip(), autoescape=True)
        )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = await db.execute(
        query.order_by(AccessKey.created_at.desc(), AccessKey.id).offset((page - 1) * 20).limit(20)
    )
    rules = await service.policy(db, actor.tenant.id)
    return KeyPage(
        items=[
            service.view(row, rules, member, name, viewer_id=actor.member.id)
            for row, member, name in rows
        ],
        total=total or 0,
        page=page,
    )


@router.get("/account/access-keys/policy", response_model=KeyPolicyView)
@router.get("/access-keys/policy", response_model=KeyPolicyView)
async def read_policy(request: Request, db: DB) -> KeyPolicyView:
    actor = await access(request, db, request.url.path == "/api/v1/access-keys/policy")
    return await service.policy(db, actor.tenant.id)


@router.put("/access-keys/policy", response_model=KeyPolicyView)
async def save_policy(request: Request, db: DB, body: KeyPolicyView, _: Mutation) -> KeyPolicyView:
    actor = await access(request, db, True, True)
    before = await service.policy(db, actor.tenant.id)
    if before.version != body.version:
        fail(409, "version_conflict", "密钥规则已变化，请刷新后重试")
    row = await db.get(AccessKeyPolicy, actor.tenant.id)
    if row is None:
        row = AccessKeyPolicy(tenant_id=actor.tenant.id)
        db.add(row)
    row.enabled, row.max_days, row.version = body.enabled, body.max_days, body.version + 1
    record(
        db,
        actor,
        "access_key.policy",
        actor.tenant.id,
        "访问密钥规则",
        {"before": before.model_dump_json(), "after": body.model_dump_json()},
    )
    await db.commit()
    return await service.policy(db, actor.tenant.id)


@router.get("/account/access-keys/resources", response_model=KeyResourcePage)
async def resources(
    request: Request,
    db: DB,
    kind: Literal["llm", "mcp"],
    page: int = Query(1, ge=1),
    q: str = Query("", max_length=100),
) -> KeyResourcePage:
    actor = await access(request, db)
    rows = await service.resources(db, actor, kind, provider(request).settings.app_url.rstrip("/"))
    if q.strip():
        rows = [r for r in rows if q.strip().casefold() in (r.name + " " + r.identifier).casefold()]
    return KeyResourcePage(items=rows[(page - 1) * 20 : page * 20], total=len(rows), page=page)


@router.post("/account/access-keys", response_model=KeyCreated)
async def create(request: Request, db: DB, body: KeyCreate, _: Mutation) -> KeyCreated:
    actor = await access(request, db)
    await limit(db, "key-create:" + str(actor.member.id), 20, 300)
    actor = await access(request, db, write=True)
    member = await db.get(Membership, actor.member.id, populate_existing=True)
    if member is None or member.source == "platform":
        fail(403, "membership_required", "请先作为成员加入组织，再创建个人访问密钥")
    rules = await service.policy(db, actor.tenant.id)
    if not rules.enabled:
        fail(403, "keys_disabled", "组织已关闭个人访问密钥")
    stamp = now()
    expires_at = body.expires_at
    if expires_at is None and rules.max_days:
        expires_at = stamp + timedelta(days=rules.max_days)
    if expires_at is not None and (
        expires_at <= stamp or expires_at > stamp + timedelta(days=rules.max_days or 3650)
    ):
        fail(422, "invalid_expiry", "有效期不符合组织规则")
    existing = await db.scalar(
        select(AccessKey.id).where(
            AccessKey.member_id == actor.member.id, AccessKey.creation_id == body.creation_id
        )
    )
    if existing:
        fail(
            409,
            "key_already_created",
            "本次密钥已创建，请在列表查看已有密钥，或删除后重新创建",
        )
    count = await db.scalar(
        select(func.count())
        .select_from(AccessKey)
        .where(
            AccessKey.member_id == actor.member.id,
            AccessKey.revoked_at.is_(None),
            or_(AccessKey.expires_at.is_(None), AccessKey.expires_at > stamp),
        )
    )
    if count and count >= 100:
        fail(409, "too_many_keys", "请先撤销不再使用的密钥（最多 100 把未过期密钥）")
    named_grants: list[dict[str, Any]] = []
    grants = body.grants or []
    for kind in {g.kind for g in grants}:
        available = {r.id: r for r in await service.resources(db, actor, kind, "")}
        if any(g.resource_id not in available for g in grants if g.kind == kind):
            fail(403, "resource_denied", "所选资源已关闭或你未获授权，请重新选择")
        named_grants.extend(
            {
                **g.model_dump(mode="json"),
                "name": available[g.resource_id].name,
                "identifier": available[g.resource_id].identifier,
            }
            for g in grants
            if g.kind == kind
        )
    assert actor.session.identity_id is not None and actor.session.authenticated_at is not None
    raw = "avk_" + secrets.token_urlsafe(32)
    row = AccessKey(
        id=uuid4(),
        tenant_id=actor.tenant.id,
        member_id=actor.member.id,
        identity_id=actor.session.identity_id,
        creation_id=body.creation_id,
        token_hash=digest(raw),
        hint=raw[:8] + "…" + raw[-4:],
        name=body.name,
        scope_mode="member" if body.grants is None else "selected",
        grants=named_grants,
        authenticated_at=actor.session.authenticated_at,
        created_at=stamp,
        expires_at=expires_at,
    )
    row.sealed_secret = provider(request).seal({"key": raw, "id": str(row.id)})
    db.add(row)
    record(
        db,
        actor,
        "access_key.created",
        row.id,
        row.name,
        {
            "scope_mode": row.scope_mode,
            "resources": str(len(row.grants)),
            "expires_at": row.expires_at.isoformat() if row.expires_at else "none",
        },
    )
    await db.commit()
    return KeyCreated(
        key=service.view(row, rules, actor.member, actor.user.name, viewer_id=actor.member.id),
        secret=raw,
        llm_base_url=provider(request).settings.app_url.rstrip("/") + "/api/llm/v1",
    )


@router.patch("/account/access-keys/{key_id}", response_model=KeyView)
@router.patch("/access-keys/{key_id}", response_model=KeyView)
async def change(key_id: UUID, request: Request, db: DB, body: KeyAction, _: Mutation) -> KeyView:
    admin = request.url.path.startswith("/api/v1/access-keys/")
    actor = await access(request, db, admin, True)
    row = await key_row(db, actor, key_id, admin)
    if row.version != body.version:
        fail(409, "version_conflict", "密钥状态已变化，请刷新后重试")
    if row.revoked_at and body.action != "delete":
        fail(409, "key_revoked", "已撤销密钥不能恢复")
    if body.action == "enable" and row.managed_disabled and not admin:
        fail(403, "managed_key_disabled", "此密钥由管理员停用，请联系管理员")
    if body.action in ("revoke", "delete"):
        row.revoked_at = row.revoked_at or now()
        row.sealed_secret = None
        if body.action == "delete":
            row.deleted_at = now()
    else:
        row.disabled = body.action == "disable"
        if admin:
            row.managed_disabled = row.disabled
    row.version += 1
    record(db, actor, "access_key." + body.action, row.id, row.name)
    await db.commit()
    member = await db.get(Membership, row.member_id)
    assert member is not None
    user = await db.get(User, member.user_id)
    assert user is not None
    return service.view(
        row, await service.policy(db, actor.tenant.id), member, user.name, viewer_id=actor.member.id
    )


@router.get("/account/access-keys/{key_id}/usage", response_model=KeyUsagePage)
@router.get("/access-keys/{key_id}/usage", response_model=KeyUsagePage)
async def usage(key_id: UUID, request: Request, db: DB, page: int = Query(1, ge=1)) -> KeyUsagePage:
    admin = request.url.path.startswith("/api/v1/access-keys/")
    actor = await access(request, db, admin)
    await key_row(db, actor, key_id, admin)
    calls = (
        select(
            ModelCall.id,
            literal("llm").label("kind"),
            CatalogModel.name.label("resource_name"),
            ModelCall.kind.label("operation"),
            ModelCall.status,
            ModelCall.duration_ms,
            ModelCall.created_at,
        )
        .join(CatalogModel)
        .where(ModelCall.access_key_id == key_id, ModelCall.tenant_id == actor.tenant.id)
    )
    mcp = select(
        McpActivity.id,
        literal("mcp"),
        McpActivity.service_name,
        McpActivity.operation,
        McpActivity.result,
        McpActivity.duration_ms,
        McpActivity.created_at,
    ).where(McpActivity.access_key_id == key_id, McpActivity.tenant_id == actor.tenant.id)
    combined = union_all(calls, mcp).subquery()
    total = await db.scalar(select(func.count()).select_from(combined))
    rows = (
        await db.execute(
            select(combined)
            .order_by(combined.c.created_at.desc(), combined.c.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).mappings()
    return KeyUsagePage(
        items=[KeyUsage.model_validate(r) for r in rows], total=total or 0, page=page
    )


@router.get(
    "/gateway/mcp/services",
    response_model=KeyResourcePage,
    dependencies=[Depends(bearer)],
    summary="个人密钥可用的 MCP 服务与协议地址",
)
async def mcp_catalog(request: Request, db: DB, page: int = Query(1, ge=1)) -> KeyResourcePage:
    actor = await service.authorize(request, db, "mcp")
    rows = await service.resources(db, actor, "mcp", provider(request).settings.app_url.rstrip("/"))
    actor.key.last_used_at = now()
    await db.commit()
    return KeyResourcePage(items=rows[(page - 1) * 20 : page * 20], total=len(rows), page=page)


@router.post("/account/access-keys/{key_id}/reveal", response_model=KeySecret)
@router.post("/access-keys/{key_id}/reveal", response_model=KeySecret)
async def reveal(
    key_id: UUID, request: Request, response: Response, db: DB, body: KeyReveal, _: Mutation
) -> KeySecret:
    admin = request.url.path.startswith("/api/v1/access-keys/")
    actor = await access(request, db, admin, True)
    # Administrator governance never grants access to another member's secret.
    row = await key_row(db, actor, key_id, False)
    if row.version != body.version:
        fail(409, "version_conflict", "密钥状态已变化，请刷新后重试")
    rules = await service.policy(db, actor.tenant.id)
    if service.state(row, rules, actor.member) not in ("active", "disabled"):
        fail(409, "key_unavailable", "此密钥已失效，不能查看")
    if not row.sealed_secret:
        fail(409, "secret_unavailable", "旧密钥未保存原文，无法恢复；请创建新密钥")
    try:
        values = provider(request).unseal(row.sealed_secret)
        raw = str(values["key"])
        if values.get("id") != str(row.id) or not secrets.compare_digest(
            digest(raw), row.token_hash
        ):
            raise ValueError("invalid sealed secret")
    except Exception:
        fail(503, "secret_unavailable", "密钥暂时无法读取，请联系管理员")
    record(db, actor, "access_key.reveal", row.id, row.name)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return KeySecret(secret=raw)
