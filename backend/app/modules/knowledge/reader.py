"""Short-lived, document-bound reader credentials; host applications own presentation."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPBearer

from app.modules.access_keys import service as keys
from app.modules.access_keys.models import AccessKey
from app.modules.auth.models import WebSession
from app.modules.auth.service import DB, now, provider
from app.modules.desktop.oidc import NativeIdentity
from app.modules.knowledge.models import KnowledgeChunk, KnowledgeGeneration
from app.modules.knowledge.preview import original_response, preview
from app.modules.knowledge.schemas import DocumentPreview, ReaderSessionView
from app.modules.knowledge.service import get_document
from app.modules.members.models import Membership
from app.modules.members.service import Access, BusinessActor, membership_state, with_departments
from app.modules.tenants.models import Installation, Tenant
from app.modules.users.models import LoginIdentity, User

bearer = HTTPBearer(
    scheme_name="KnowledgeReader",
    auto_error=False,
    description="单文档、短期 avr_ 阅读凭证，不接受模型密钥或 Web Cookie 代替",
)
router = APIRouter(
    prefix="/api/v1/knowledge-reader", tags=["knowledge-reader"], dependencies=[Depends(bearer)]
)


def normalize_parent(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(c.isspace() for c in value)
            or any(c in value for c in "'\";\\")
            or parsed.scheme == "http"
            and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError()
        port = parsed.port
        host = parsed.hostname.encode("idna").decode()
        if ":" in host:
            host = f"[{host}]"
        suffix = f":{port}" if port and port != (443 if parsed.scheme == "https" else 80) else ""
        return f"{parsed.scheme}://{host}{suffix}"
    except (ValueError, UnicodeError):
        raise HTTPException(
            422, "请填写完整的 HTTPS 来源地址，不包含路径；本地可使用 HTTP"
        ) from None


async def issue(
    request: Request,
    db: DB,
    actor: Access | keys.KeyActor,
    base_id: UUID,
    chunk_id: UUID,
    parent_origin: str,
) -> ReaderSessionView:
    parent = normalize_parent(parent_origin)
    chunk = await db.get(KnowledgeChunk, chunk_id)
    generation = await db.get(KnowledgeGeneration, chunk.generation_id) if chunk else None
    if not chunk or not generation:
        raise HTTPException(404, "引用不存在")
    _, doc = await get_document(db, actor, base_id, generation.document_id)
    expires = now() + timedelta(minutes=10)
    if isinstance(actor, keys.KeyActor):
        origin_kind, origin_id = "key", actor.key.id
        if actor.key.expires_at:
            expires = min(expires, actor.key.expires_at)
    else:
        origin_kind, origin_id = "web", actor.session.id
        expires = min(expires, actor.session.expires_at)
    token = "avr_" + provider(request).seal(
        {
            "purpose": "knowledge-reader-v1",
            "exp": expires.timestamp(),
            "parent": parent,
            "kind": origin_kind,
            "credential": str(origin_id),
            "tenant": str(actor.tenant.id),
            "member": str(actor.member.id),
            "base": str(base_id),
            "document": str(doc.id),
            "generation": str(generation.id),
            "chunk": str(chunk.id),
        }
    )
    return ReaderSessionView(
        viewer_url=provider(request).settings.app_url.rstrip("/")
        + "/embed/knowledge?"
        + urlencode({"parent_origin": parent}),
        token=token,
        expires_at=expires,
        parent_origin=parent,
    )


@dataclass
class ReaderAccess:
    actor: BusinessActor
    base_id: UUID
    document_id: UUID
    generation_id: UUID
    chunk_id: UUID


async def authorize(request: Request, db: DB) -> ReaderAccess:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer avr_") or len(header) > 4096:
        raise HTTPException(401, "原文预览凭证无效")
    try:
        claims = provider(request).unseal(header[11:])
        if (
            claims["purpose"] != "knowledge-reader-v1"
            or datetime.fromtimestamp(claims["exp"], UTC) <= now()
            or claims["parent"] != request.headers.get("x-knowledge-parent")
        ):
            raise ValueError()
        tenant_id, member_id, credential_id = (
            UUID(claims[k]) for k in ("tenant", "member", "credential")
        )
        base_id, document_id, generation_id, chunk_id = (
            UUID(claims[k]) for k in ("base", "document", "generation", "chunk")
        )
    except (InvalidToken, ValueError, KeyError, TypeError, OverflowError):
        raise HTTPException(401, "原文预览已过期或凭证无效，请重新打开引用") from None
    tenant = await db.get(Tenant, tenant_id, populate_existing=True)
    member = await db.get(Membership, member_id, populate_existing=True)
    if not member or not tenant or member.tenant_id != tenant.id:
        raise HTTPException(403, "原文访问权限已变化")
    installation = await db.get(Installation, 1)
    if provider(request).settings.platform_edition == "community" and (
        not installation or installation.tenant_id != tenant_id
    ):
        raise HTTPException(403, "组织不可用")
    identity_id = None
    stamp = None
    key = None
    if claims["kind"] == "key":
        key = await db.get(AccessKey, credential_id, populate_existing=True)
        if (
            not key
            or key.member_id != member_id
            or key.tenant_id != tenant_id
            or keys.state(key, await keys.policy(db, tenant_id), member) != "active"
        ):
            raise HTTPException(401, "原文调用密钥已失效")
        identity_id, stamp = key.identity_id, key.authenticated_at
    elif claims["kind"] == "web":
        session = await db.get(WebSession, credential_id, populate_existing=True)
        if (
            not session
            or not session.tokens
            or session.requires_reauth
            or session.expires_at <= now()
            or session.absolute_expires_at
            and session.absolute_expires_at <= now()
            or session.tenant_id not in {None, tenant_id}
        ):
            raise HTTPException(401, "原文调用会话已失效")
        identity_id, stamp = session.identity_id, session.authenticated_at
    if not identity_id or not stamp or membership_state(tenant, member, stamp):
        raise HTTPException(403, "原文访问权限已变化")
    identity = await db.get(LoginIdentity, identity_id)
    user = await db.get(User, member.user_id)
    if (
        not identity
        or not user
        or identity.user_id != user.id
        or identity.issuer != provider(request).settings.oidc_issuer
    ):
        raise HTTPException(401, "原文调用身份已失效")
    await NativeIdentity(provider(request)).account_valid(identity.subject, stamp)
    actor: BusinessActor = (
        keys.KeyActor(user, member, tenant, key) if key else BusinessActor(user, member, tenant)
    )
    actor = await with_departments(db, actor)
    if not keys.permits(actor, "knowledge", base_id, "read"):
        raise HTTPException(403, "此密钥无权读取知识库")
    await get_document(db, actor, base_id, document_id)
    return ReaderAccess(actor, base_id, document_id, generation_id, chunk_id)


@router.get(
    "/manifest", response_model=DocumentPreview, summary="读取被授权原文的展示信息与高亮位置"
)
async def manifest(request: Request, db: DB) -> DocumentPreview:
    grant = await authorize(request, db)
    result = await preview(
        db, grant.actor, grant.base_id, grant.document_id, grant.generation_id, grant.chunk_id
    )
    result.source_url = "/api/v1/knowledge-reader/source"
    return result


@router.get("/source", response_class=Response, summary="读取凭证绑定原件；每次重新验证当前权限")
async def source(request: Request, db: DB) -> Response:
    grant = await authorize(request, db)
    _, doc = await get_document(db, grant.actor, grant.base_id, grant.document_id)
    await db.refresh(doc, ["data"])
    return original_response(doc)
