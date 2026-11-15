"""Organization-scoped knowledge APIs. Mutations require a Web session and CSRF."""

import asyncio
import hashlib
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy import update as sql_update

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, now, provider
from app.modules.integrations import service as integrations
from app.modules.integrations.actor import ApplicationActor
from app.modules.knowledge.chunk_preview import build_preview, preview_token
from app.modules.knowledge.credentials import account_hint
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeGeneration,
    KnowledgeSettings,
    ParserCredential,
)
from app.modules.knowledge.parsing import MAX_FILE, inspect_file
from app.modules.knowledge.preview import original_response, preview
from app.modules.knowledge.reader import issue
from app.modules.knowledge.retrieval import citation, search
from app.modules.knowledge.schemas import (
    Chunking,
    ChunkPreviewInput,
    ChunkPreviewView,
    ChunkView,
    CitationView,
    CredentialBatchCreate,
    CredentialCreate,
    CredentialRename,
    CredentialView,
    DocumentDetail,
    DocumentPreview,
    DocumentView,
    KnowledgeCreate,
    KnowledgeDefaults,
    KnowledgeDefaultsView,
    KnowledgeIconUpdate,
    KnowledgePage,
    KnowledgeUpdate,
    KnowledgeView,
    ModelOption,
    ParsedSource,
    ReaderSessionInput,
    ReaderSessionView,
    RebuildInput,
    RetrievalInput,
    RetrievalPolicy,
    RetrievalView,
    SourceBlock,
)
from app.modules.knowledge.service import (
    KnowledgeActor,
    access,
    base_view,
    can_manage,
    default_retrieval,
    document_view,
    embedding_profile,
    enqueue,
    get_base,
    get_document,
    index_profile,
    list_filter,
    require_manage,
    resolve_embedding,
    retrieval_model,
    validate_scope,
)
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import CatalogModel
from app.modules.members.service import record
from app.modules.tenants.models import Tenant

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.get(
    "/defaults", response_model=KnowledgeDefaultsView, summary="读取当前组织的知识库默认配置"
)
async def defaults(request: Request, db: DB) -> KnowledgeDefaultsView:
    actor = await access(request, db)
    if actor.member.role != "administrator":
        raise HTTPException(403, "仅管理员可管理默认配置")
    row = await db.get(KnowledgeSettings, actor.tenant.id)
    options = await model_options(db, actor.tenant.id)
    credentials = await db.scalars(
        select(ParserCredential)
        .where(ParserCredential.tenant_id == actor.tenant.id)
        .order_by(ParserCredential.id)
    )
    return KnowledgeDefaultsView(
        version=row.version if row else 0,
        embedding_model_id=row.embedding_model_id if row else None,
        rerank_model_id=row.rerank_model_id if row else None,
        rerank_enabled=row.rerank_enabled if row else False,
        credentials=[CredentialView.model_validate(c) for c in credentials],
        models=options,
    )


async def model_options(db: DB, tenant_id: UUID) -> list[ModelOption]:
    options = []
    for model in await db.scalars(
        select(CatalogModel).where(
            CatalogModel.tenant_id == tenant_id, CatalogModel.archived.is_(False)
        )
    ):
        config = CatalogInput.model_validate(model.configuration)
        for kind in ("embedding", "rerank"):
            op = config.for_operation(kind)
            if (
                op
                and op.access.enabled
                and (
                    kind != "embedding"
                    or (op.retrieval.dimensions and op.retrieval.embedding_space)
                )
            ):
                options.append(
                    ModelOption(
                        id=model.id, name=config.name, kind=kind, dimensions=op.retrieval.dimensions
                    )
                )
    return options


@router.put(
    "/defaults", response_model=KnowledgeDefaultsView, summary="设置组织默认模型并授权知识库调用"
)
async def save_defaults(
    body: KnowledgeDefaults, request: Request, db: DB, _: Mutation
) -> KnowledgeDefaultsView:
    actor = await access(request, db, write=True)
    await db.scalar(select(Tenant.id).where(Tenant.id == actor.tenant.id).with_for_update())
    row = await db.get(KnowledgeSettings, actor.tenant.id)
    if body.version != (row.version if row else 0):
        raise HTTPException(409, "默认配置已变化，请刷新")
    selections: tuple[tuple[UUID | None, Literal["embedding", "rerank"], bool], ...] = (
        (
            body.embedding_model_id,
            "embedding",
            row is None or body.embedding_model_id != row.embedding_model_id,
        ),
        (
            body.rerank_model_id,
            "rerank",
            row is None
            or body.rerank_model_id != row.rerank_model_id
            or (body.rerank_enabled and not row.rerank_enabled),
        ),
    )
    # An unavailable saved model must not block changes to the other field.
    for ident, kind, changed in selections:
        if ident and changed:
            if kind == "embedding":
                await resolve_embedding(db, actor.tenant.id, ident)
            else:
                await retrieval_model(db, actor.tenant.id, ident, kind)
    if body.rerank_enabled and not body.rerank_model_id:
        raise HTTPException(422, "请选择重排序模型")
    if not row:
        row = KnowledgeSettings(tenant_id=actor.tenant.id, version=0)
        db.add(row)
    row.embedding_model_id, row.rerank_model_id, row.rerank_enabled = (
        body.embedding_model_id,
        body.rerank_model_id,
        body.rerank_enabled,
    )
    row.version += 1
    record(db, actor, "knowledge.defaults", actor.tenant.id, "知识库默认配置")
    await db.commit()
    return await defaults(request, db)


@router.post(
    "/credentials",
    response_model=CredentialView,
    status_code=201,
    summary="添加加密保存的 MinerU 凭据",
)
async def add_credential(
    body: CredentialCreate, request: Request, db: DB, _: Mutation
) -> CredentialView:
    actor = await access(request, db, write=True)
    count = await db.scalar(
        select(func.count())
        .select_from(ParserCredential)
        .where(ParserCredential.tenant_id == actor.tenant.id)
    )
    if (count or 0) >= 20:
        raise HTTPException(422, "最多保存 20 个解析凭据")
    row = ParserCredential(
        tenant_id=actor.tenant.id,
        name=body.name,
        account=body.account,
        secret=provider(request).seal({"key": body.key}),
    )
    db.add(row)
    await db.flush()
    record(db, actor, "knowledge.credential.create", row.id, row.name)
    view = CredentialView.model_validate(row)
    await db.commit()
    return view


@router.post(
    "/credentials/batch",
    response_model=list[CredentialView],
    status_code=201,
    summary="批量添加 MinerU Key，自动去重并加密保存",
)
async def add_credentials(
    body: CredentialBatchCreate, request: Request, db: DB, _: Mutation
) -> list[CredentialView]:
    actor = await access(request, db, write=True)
    identity = provider(request)
    rows = list(
        await db.scalars(
            select(ParserCredential).where(ParserCredential.tenant_id == actor.tenant.id)
        )
    )
    existing = {identity.unseal(row.secret)["key"]: row for row in rows}
    keys = list(dict.fromkeys(secret.get_secret_value().strip() for secret in body.keys))
    if any(len(key) < 10 or any(c.isspace() or c in ",，" for c in key) for key in keys):
        raise HTTPException(422, "Key 格式不正确，请用逗号分隔后重试")
    new_count = sum(key not in existing for key in keys)
    if len(rows) + new_count > 20:
        raise HTTPException(422, "最多保存 20 个解析凭据")
    result = []
    added = 0
    existing_names = {row.name for row in rows}
    next_number = 1
    for key in keys:
        row = existing.get(key)
        if row is None:
            added += 1
            if body.name:
                name = f"{body.name} {added}" if new_count > 1 else body.name
            else:
                while f"Key {next_number}" in existing_names:
                    next_number += 1
                name = f"Key {next_number}"
                next_number += 1
            row = ParserCredential(
                tenant_id=actor.tenant.id,
                name=name,
                account=account_hint(key),
                secret=identity.seal({"key": key}),
            )
            db.add(row)
            await db.flush()
            record(db, actor, "knowledge.credential.create", row.id, row.name)
            rows.append(row)
        result.append(CredentialView.model_validate(row))
    await db.commit()
    return result


async def lock_credential(db: DB, tenant_id: UUID, credential_id: UUID) -> ParserCredential:
    row = await db.scalar(
        select(ParserCredential)
        .where(ParserCredential.id == credential_id, ParserCredential.tenant_id == tenant_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "凭据不存在")
    return row


@router.put(
    "/credentials/{credential_id}", response_model=CredentialView, summary="启用或停用解析凭据"
)
async def toggle_credential(
    credential_id: UUID, enabled: bool, request: Request, db: DB, _: Mutation
) -> CredentialView:
    actor = await access(request, db, write=True)
    row = await lock_credential(db, actor.tenant.id, credential_id)
    row.enabled = enabled
    if enabled:
        row.error, row.cooldown_until = "", None
    record(db, actor, "knowledge.credential.update", row.id, row.name)
    await db.commit()
    return CredentialView.model_validate(row)


@router.patch(
    "/credentials/{credential_id}", response_model=CredentialView, summary="修改解析凭据名称"
)
async def rename_credential(
    credential_id: UUID, body: CredentialRename, request: Request, db: DB, _: Mutation
) -> CredentialView:
    actor = await access(request, db, write=True)
    row = await lock_credential(db, actor.tenant.id, credential_id)
    row.name = body.name
    record(db, actor, "knowledge.credential.rename", row.id, row.name)
    await db.commit()
    return CredentialView.model_validate(row)


@router.delete(
    "/credentials/{credential_id}",
    status_code=204,
    summary="删除 MinerU 解析凭据",
    responses={409: {"description": "此凭据仍有解析任务在处理"}},
)
async def delete_credential(credential_id: UUID, request: Request, db: DB, _: Mutation) -> Response:
    actor = await access(request, db, write=True)
    row = await lock_credential(db, actor.tenant.id, credential_id)
    pending = await db.scalar(
        select(KnowledgeGeneration.id)
        .where(
            KnowledgeGeneration.credential_id == row.id,
            KnowledgeGeneration.status.in_(("queued", "parsing", "waiting")),
            (KnowledgeGeneration.batch_id.is_not(None) | KnowledgeGeneration.submission_pending),
        )
        .limit(1)
    )
    if pending is not None:
        raise HTTPException(409, "此 Key 仍有解析任务在处理，请等待任务结束后再删除")
    await db.execute(
        sql_update(KnowledgeGeneration)
        .where(KnowledgeGeneration.credential_id == row.id)
        .values(credential_id=None)
    )
    record(db, actor, "knowledge.credential.delete", row.id, row.name)
    await db.delete(row)
    await db.commit()
    return Response(status_code=204)


@router.get("", response_model=KnowledgePage, summary="列出本人有权访问的知识库")
async def bases(
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
) -> KnowledgePage:
    return await list_bases(db, await access(request, db), q, page)


async def list_bases(db: DB, actor: KnowledgeActor, q: str, page: int) -> KnowledgePage:
    filters = [KnowledgeBase.tenant_id == actor.tenant.id, KnowledgeBase.archived.is_(False)]
    if q:
        filters.append(KnowledgeBase.name.icontains(q, autoescape=True))
    if isinstance(actor, ApplicationActor) or actor.member.role != "administrator":
        filters.append(list_filter(actor))
    total = await db.scalar(select(func.count()).select_from(KnowledgeBase).where(*filters))
    rows = await db.scalars(
        select(KnowledgeBase)
        .where(*filters)
        .order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.id)
        .offset((page - 1) * 20)
        .limit(20)
    )
    return KnowledgePage(items=[await base_view(db, row, actor) for row in rows], total=total or 0)


@router.post(
    "", response_model=KnowledgeView, status_code=201, summary="创建知识库并保存生效的检索配置"
)
async def create(body: KnowledgeCreate, request: Request, db: DB, _: Mutation) -> KnowledgeView:
    return await create_base(db, await access(request, db, write=True), body)


async def create_base(
    db: DB, actor: KnowledgeActor, body: KnowledgeCreate, creation_id: UUID | None = None
) -> KnowledgeView:
    grants = await validate_scope(db, actor, body)
    await db.scalar(select(Tenant.id).where(Tenant.id == actor.tenant.id).with_for_update())
    app_id = actor.application.id if isinstance(actor, ApplicationActor) else None
    fingerprint = None
    if app_id is not None and creation_id is not None:
        fingerprint = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
        previous = await db.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.application_id == app_id, KnowledgeBase.creation_id == creation_id
            )
        )
        if previous:
            if previous.creation_fingerprint != fingerprint or previous.archived:
                raise HTTPException(409, "创建标识已使用，请使用新的 creation_id")
            return await base_view(db, previous, actor)
    settings = await db.get(KnowledgeSettings, actor.tenant.id)
    if body.defaults_version is not None and body.defaults_version != (
        settings.version if settings else 0
    ):
        raise HTTPException(409, "组织默认配置已变化，请确认后重试")
    policy = body.retrieval or default_retrieval(settings)
    if policy.rerank_model_id:
        await retrieval_model(db, actor.tenant.id, policy.rerank_model_id, "rerank")
    profile = (
        await resolve_embedding(db, actor.tenant.id, policy.embedding_model_id)
        if policy.mode != "keyword" and policy.embedding_model_id
        else {}
    )
    row = KnowledgeBase(
        tenant_id=actor.tenant.id,
        application_id=app_id,
        creation_id=creation_id,
        creation_fingerprint=fingerprint,
        **body.model_dump(
            mode="json",
            exclude={"department_grants", "retrieval", "defaults_version", "icon_selection"},
        ),
        icon_selection=body.icon_selection.model_dump() if body.icon_selection else None,
        department_grants=grants,
        embedding_profile=profile,
        retrieval=(
            policy.model_dump(mode="json")
            if body.retrieval is not None or body.defaults_version is not None
            else None
        ),
    )
    db.add(row)
    await db.flush()
    record(db, actor, "knowledge.create", row.id, row.name)
    result = await base_view(db, row, actor)
    await db.commit()
    return result


@router.get("/{base_id}", response_model=KnowledgeView, summary="读取知识库设置与处理状态")
async def detail(base_id: UUID, request: Request, db: DB) -> KnowledgeView:
    actor = await access(request, db)
    return await base_view(db, await get_base(db, actor, base_id), actor)


@router.put(
    "/{base_id}", response_model=KnowledgeView, summary="更新知识库设置；已有文档需单独重新处理"
)
async def update(
    base_id: UUID, body: KnowledgeUpdate, request: Request, db: DB, _: Mutation
) -> KnowledgeView:
    return await update_base(db, await access(request, db, write=True), base_id, body)


async def update_base(
    db: DB, actor: KnowledgeActor, base_id: UUID, body: KnowledgeUpdate
) -> KnowledgeView:
    row = await get_base(db, actor, base_id, lock=True)
    require_manage(row, actor)
    if row.version != body.version:
        raise HTTPException(409, "知识库已变化，请刷新")
    grants = await validate_scope(db, actor, body)
    if body.retrieval is not None:
        await update_retrieval(db, row, body.retrieval)
    for key, value in body.model_dump(
        mode="json", exclude={"version", "department_grants", "retrieval", "icon_selection"}
    ).items():
        setattr(row, key, value)
    if body.icon_selection is not None:
        row.icon_selection = body.icon_selection.model_dump()
    row.department_grants, row.updated_at = grants, now()
    row.version += 1
    record(db, actor, "knowledge.update", row.id, row.name)
    result = await base_view(db, row, actor)
    await db.commit()
    return result


@router.patch("/{base_id}/icon", response_model=KnowledgeView, summary="更换知识库头像或恢复默认")
async def update_icon(
    base_id: UUID, body: KnowledgeIconUpdate, request: Request, db: DB, _: Mutation
) -> KnowledgeView:
    actor = await access(request, db, write=True)
    row = await get_base(db, actor, base_id, lock=True)
    if row.version != body.version:
        raise HTTPException(409, "知识库已变化，请刷新后重试")
    row.icon_selection = body.icon_selection.model_dump()
    row.updated_at = now()
    row.version += 1
    record(db, actor, "knowledge.icon.update", row.id, row.name)
    result = await base_view(db, row, actor)
    await db.commit()
    return result


async def update_retrieval(db: DB, base: KnowledgeBase, policy: RetrievalPolicy) -> None:
    if policy.rerank_model_id and str(policy.rerank_model_id) != (base.retrieval or {}).get(
        "rerank_model_id"
    ):
        await retrieval_model(db, base.tenant_id, policy.rerank_model_id, "rerank")
    model_id = policy.embedding_model_id
    if (
        policy.mode != "keyword"
        and model_id
        and str(model_id) != base.embedding_profile.get("model_id")
    ):
        if base.embedding_profile and await db.scalar(
            select(KnowledgeDocument.id)
            .where(KnowledgeDocument.base_id == base.id, KnowledgeDocument.deleted_at.is_(None))
            .limit(1)
        ):
            raise HTTPException(409, "已有文档的向量模型不能直接更换，请使用原模型或新建知识库")
        base.embedding_profile = await resolve_embedding(db, base.tenant_id, model_id)
    base.retrieval = policy.model_dump(mode="json")


@router.delete("/{base_id}", status_code=204, summary="归档知识库并立即停止原文和检索访问")
async def archive(base_id: UUID, request: Request, db: DB, _: Mutation) -> Response:
    return await archive_base(db, await access(request, db, write=True), base_id)


async def archive_base(db: DB, actor: KnowledgeActor, base_id: UUID) -> Response:
    row = await get_base(db, actor, base_id, lock=True)
    require_manage(row, actor)
    row.archived = True
    record(db, actor, "knowledge.archive", row.id, row.name)
    await db.commit()
    return Response(status_code=204)


@router.get(
    "/{base_id}/documents", response_model=list[DocumentView], summary="列出文档及最新处理进度"
)
async def documents(base_id: UUID, request: Request, db: DB) -> list[DocumentView]:
    return await list_documents(db, await access(request, db), base_id)


async def list_documents(db: DB, actor: KnowledgeActor, base_id: UUID) -> list[DocumentView]:
    await get_base(db, actor, base_id)
    rows = await db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.base_id == base_id, KnowledgeDocument.deleted_at.is_(None))
        .order_by(KnowledgeDocument.created_at.desc())
    )
    return [await document_view(db, row) for row in rows]


@router.post(
    "/{base_id}/documents",
    response_model=DocumentView,
    status_code=201,
    summary="上传文档原件并启动异步解析；upload_id 保证重试幂等",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(
    base_id: UUID, upload_id: UUID, filename: str, request: Request, db: DB, _: Mutation
) -> DocumentView:
    return await upload_document(
        db, await access(request, db, write=True), base_id, upload_id, filename, request
    )


async def upload_document(
    db: DB, actor: KnowledgeActor, base_id: UUID, upload_id: UUID, filename: str, request: Request
) -> DocumentView:
    require_manage(await get_base(db, actor, base_id), actor)
    content = bytearray()
    async for part in request.stream():
        content.extend(part)
        if len(content) > MAX_FILE:
            raise HTTPException(413, "单文件最多 20 MiB")
    try:
        extension, media = inspect_file(filename, bytes(content))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    digest = hashlib.sha256(content).hexdigest()
    if isinstance(actor, ApplicationActor):
        await db.scalar(select(Tenant.id).where(Tenant.id == actor.tenant.id).with_for_update())
        actor = await integrations.authorize(request, db, "knowledge_write")
    base = await get_base(db, actor, base_id, lock=True)
    require_manage(base, actor)
    old = await db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.base_id == base_id, KnowledgeDocument.upload_id == upload_id
        )
    )
    if old:
        if old.sha256 != digest or old.filename != filename or old.deleted_at:
            raise HTTPException(409, "上传标识已使用，请重新选择文件")
        return await document_view(db, old)
    count = await db.scalar(
        select(func.count())
        .select_from(KnowledgeDocument)
        .where(KnowledgeDocument.base_id == base_id, KnowledgeDocument.deleted_at.is_(None))
    )
    if (count or 0) >= 100:
        raise HTTPException(422, "当前版本每库最多 100 个文档")
    row = KnowledgeDocument(
        base_id=base_id,
        upload_id=upload_id,
        filename=filename,
        media_type=media,
        data=bytes(content),
        size=len(content),
        sha256=digest,
    )
    db.add(row)
    await db.flush()
    await enqueue(db, base, row, actor)
    record(db, actor, "knowledge.document.upload", row.id, row.filename)
    result = await document_view(db, row)
    await db.commit()
    return result


@router.get(
    "/{base_id}/documents/{document_id}",
    response_model=DocumentDetail,
    summary="分页读取切片与原文位置；可查看历史切片版本",
)
async def document(
    base_id: UUID,
    document_id: UUID,
    request: Request,
    db: DB,
    generation_id: UUID | None = None,
    page: int = Query(default=1, ge=1),
    q: str = Query(default="", max_length=200),
) -> DocumentDetail:
    return await document_detail(
        db, await access(request, db), base_id, document_id, generation_id, page, q
    )


async def document_detail(
    db: DB,
    actor: KnowledgeActor,
    base_id: UUID,
    document_id: UUID,
    generation_id: UUID | None,
    page: int,
    q: str,
) -> DocumentDetail:
    base, row = await get_document(db, actor, base_id, document_id)
    ident = generation_id or row.latest_generation_id
    generation = await db.get(KnowledgeGeneration, ident) if ident else None
    if generation_id and (not generation or generation.document_id != row.id):
        raise HTTPException(404, "版本不存在")
    filters = [KnowledgeChunk.generation_id == ident]
    if q.strip():
        filters.append(KnowledgeChunk.content.icontains(q.strip(), autoescape=True))
    chunks = await db.scalars(
        select(KnowledgeChunk)
        .where(*filters)
        .order_by(KnowledgeChunk.sequence)
        .offset((page - 1) * 50)
        .limit(50)
    )
    total = await db.scalar(select(func.count()).select_from(KnowledgeChunk).where(*filters))
    return DocumentDetail(
        **(await document_view(db, row, ident)).model_dump(),
        chunks=[ChunkView.model_validate(c) for c in chunks],
        total_chunks=total or 0,
        can_manage=can_manage(base, actor),
        chunking=Chunking.model_validate(generation.chunking) if generation else None,
        source_url=(
            f"/api/integrations/v1/knowledge/bases/{base_id}/documents/{document_id}/source"
            if isinstance(actor, ApplicationActor)
            else f"/api/v1/knowledge/{base_id}/documents/{document_id}/source"
        ),
    )


@router.post(
    "/{base_id}/documents/{document_id}/chunk-preview",
    response_model=ChunkPreviewView,
    summary="使用已解析原文试算切片，不写入索引或调用模型",
)
async def chunk_preview(
    base_id: UUID,
    document_id: UUID,
    body: ChunkPreviewInput,
    request: Request,
    response: Response,
    db: DB,
    _: Mutation,
) -> ChunkPreviewView:
    return await preview_document_chunks(
        db, await access(request, db, write=True), base_id, document_id, body, response
    )


async def preview_document_chunks(
    db: DB,
    actor: KnowledgeActor,
    base_id: UUID,
    document_id: UUID,
    body: ChunkPreviewInput,
    response: Response,
) -> ChunkPreviewView:
    base, row = await get_document(db, actor, base_id, document_id)
    require_manage(base, actor)
    generation = await db.get(KnowledgeGeneration, body.generation_id)
    if not generation or generation.document_id != row.id:
        raise HTTPException(404, "文档版本不存在")
    if row.latest_generation_id != generation.id:
        raise HTTPException(409, "文档处理版本已变化，请重新打开文档")
    await db.refresh(generation, ["blocks"])
    if not generation.blocks:
        raise HTTPException(409, "文档尚未完成解析，请等待解析完成后再预览")
    await db.refresh(row, ["data"])
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return await asyncio.to_thread(
            build_preview, body, generation.blocks, index_profile(base), row.data, row.media_type
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get(
    "/{base_id}/documents/{document_id}/source",
    summary="在当前权限下读取原件，禁止公共缓存",
    response_class=Response,
)
async def source(base_id: UUID, document_id: UUID, request: Request, db: DB) -> Response:
    actor = await access(request, db)
    base, row = await get_document(db, actor, base_id, document_id)
    await db.refresh(row, ["data"])
    return original_response(row)


@router.post(
    "/{base_id}/documents/{document_id}/rebuild",
    response_model=DocumentView,
    summary="创建新的切片版本；成功前保留旧索引",
)
async def rebuild(
    base_id: UUID, document_id: UUID, body: RebuildInput, request: Request, db: DB, _: Mutation
) -> DocumentView:
    return await rebuild_document(
        db, await access(request, db, write=True), base_id, document_id, body
    )


async def rebuild_document(
    db: DB, actor: KnowledgeActor, base_id: UUID, document_id: UUID, body: RebuildInput
) -> DocumentView:
    base, row = await get_document(db, actor, base_id, document_id, lock_base=True)
    require_manage(base, actor)
    if row.latest_generation_id != body.generation_id:
        raise HTTPException(409, "文档处理版本已变化，请刷新")
    previous = await db.get(KnowledgeGeneration, row.latest_generation_id)
    if previous and previous.lease_until and previous.lease_until > now():
        raise HTTPException(409, "文档正在处理中，请稍后重试")
    if body.use_current_defaults and base.retrieval is None:
        profile = await embedding_profile(db, base.tenant_id)
        if base.embedding_profile and base.embedding_profile != profile:
            raise HTTPException(409, "已有向量空间不能直接更换，请新建知识库后重新导入")
        base.embedding_profile = profile
    if body.preview_token:
        config = body.chunking or Chunking.model_validate(base.chunking)
        if body.preview_token != preview_token(body.generation_id, config, index_profile(base)):
            raise HTTPException(409, "切片配置或模型已变化，请重新预览后再应用")
    await enqueue(db, base, row, actor, body.chunking)
    record(db, actor, "knowledge.document.rebuild", row.id, row.filename)
    result = await document_view(db, row)
    await db.commit()
    return result


@router.delete(
    "/{base_id}/documents/{document_id}",
    status_code=204,
    summary="删除文档并撤销所有版本的引用访问",
)
async def delete_document(
    base_id: UUID, document_id: UUID, request: Request, db: DB, _: Mutation
) -> Response:
    return await remove_document(db, await access(request, db, write=True), base_id, document_id)


async def remove_document(
    db: DB, actor: KnowledgeActor, base_id: UUID, document_id: UUID
) -> Response:
    base, row = await get_document(db, actor, base_id, document_id, lock_base=True)
    require_manage(base, actor)
    row.deleted_at = now()
    record(db, actor, "knowledge.document.delete", row.id, row.filename)
    await db.commit()
    return Response(status_code=204)


@router.post(
    "/{base_id}/search",
    response_model=RetrievalView,
    summary="在授权知识库内检索；向量与重排序调用沿用模型计费",
)
async def retrieve(
    base_id: UUID, body: RetrievalInput, request: Request, db: DB, _: Mutation
) -> RetrievalView:
    actor = await access(request, db)
    base = await get_base(db, actor, base_id)
    return await search(request, db, base, actor, body)


@router.get(
    "/{base_id}/citations/{chunk_id}",
    response_model=CitationView,
    summary="读取稳定引用；历史版本仍检查当前文档权限",
)
async def reference(base_id: UUID, chunk_id: UUID, request: Request, db: DB) -> CitationView:
    return await citation_detail(db, await access(request, db), base_id, chunk_id)


async def citation_detail(
    db: DB, actor: KnowledgeActor, base_id: UUID, chunk_id: UUID
) -> CitationView:
    chunk = await db.get(KnowledgeChunk, chunk_id)
    generation = await db.get(KnowledgeGeneration, chunk.generation_id) if chunk else None
    if not chunk or not generation:
        raise HTTPException(404, "引用不存在")
    base, doc = await get_document(db, actor, base_id, generation.document_id)
    return citation(base, doc, chunk, application=isinstance(actor, ApplicationActor))


@router.get(
    "/{base_id}/documents/{document_id}/parsed-source",
    response_model=ParsedSource,
    summary="读取原文结构块，支持按块定位并分页",
)
async def parsed_source(
    base_id: UUID,
    document_id: UUID,
    request: Request,
    db: DB,
    generation_id: UUID,
    offset: int = Query(default=0, ge=0),
    block_id: str | None = Query(default=None, max_length=100),
) -> ParsedSource:
    actor = await access(request, db)
    await get_document(db, actor, base_id, document_id)
    generation = await db.get(KnowledgeGeneration, generation_id)
    if not generation or generation.document_id != document_id:
        raise HTTPException(404, "原文版本不存在")
    await db.refresh(generation, ["blocks"])
    blocks = generation.blocks
    if block_id is not None:
        index = next((i for i, block in enumerate(blocks) if block["block_id"] == block_id), None)
        if index is None:
            raise HTTPException(404, "原文位置不存在")
        offset = index // 50 * 50
    return ParsedSource(
        blocks=[SourceBlock.model_validate(b) for b in blocks[offset : offset + 50]],
        total=len(blocks),
        offset=offset,
    )


@router.get(
    "/{base_id}/documents/{document_id}/preview",
    response_model=DocumentPreview,
    summary="读取原件展示信息与引用高亮位置，不返回替代原文的解析文本",
)
async def original_preview(
    base_id: UUID,
    document_id: UUID,
    request: Request,
    db: DB,
    generation_id: UUID | None = None,
    chunk_id: UUID | None = None,
) -> DocumentPreview:
    actor = await access(request, db)
    return await preview(db, actor, base_id, document_id, generation_id, chunk_id)


@router.post(
    "/{base_id}/citations/{chunk_id}/reader-session",
    response_model=ReaderSessionView,
    summary="签发单文档短期嵌入凭证；宿主自行选择弹窗、侧栏或全屏",
)
async def reader_session(
    base_id: UUID,
    chunk_id: UUID,
    body: ReaderSessionInput,
    request: Request,
    db: DB,
    _: Mutation,
) -> ReaderSessionView:
    actor = await access(request, db)
    return await issue(request, db, actor, base_id, chunk_id, body.parent_origin)
