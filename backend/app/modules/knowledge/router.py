"""Organization-scoped knowledge APIs. Mutations require a Web session and CSRF."""

import hashlib
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, now, provider
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
    ChunkView,
    CitationView,
    CredentialBatchCreate,
    CredentialCreate,
    CredentialView,
    DocumentDetail,
    DocumentPreview,
    DocumentView,
    KnowledgeCreate,
    KnowledgeDefaults,
    KnowledgeDefaultsView,
    KnowledgePage,
    KnowledgeUpdate,
    KnowledgeView,
    ModelOption,
    ParsedSource,
    ReaderSessionInput,
    ReaderSessionView,
    RebuildInput,
    RetrievalInput,
    RetrievalView,
    SourceBlock,
)
from app.modules.knowledge.service import (
    access,
    base_view,
    document_view,
    embedding_profile,
    enqueue,
    get_base,
    get_document,
    list_filter,
    validate_scope,
)
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import CatalogModel
from app.modules.members.models import Membership
from app.modules.members.service import record
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.get(
    "/defaults", response_model=KnowledgeDefaultsView, summary="读取当前组织的知识库默认配置"
)
async def defaults(request: Request, db: DB) -> KnowledgeDefaultsView:
    actor = await access(request, db)
    if actor.member.role != "administrator":
        raise HTTPException(403, "仅管理员可管理默认配置")
    row = await db.get(KnowledgeSettings, actor.tenant.id)
    options = []
    for model in await db.scalars(
        select(CatalogModel).where(
            CatalogModel.tenant_id == actor.tenant.id, CatalogModel.archived.is_(False)
        )
    ):
        config = CatalogInput.model_validate(model.configuration)
        for kind in ("embedding", "rerank"):
            op = config.for_operation(kind)
            if op and op.access.enabled:
                options.append(
                    ModelOption(
                        id=model.id, name=config.name, kind=kind, dimensions=op.retrieval.dimensions
                    )
                )
    credentials = await db.scalars(
        select(ParserCredential)
        .where(ParserCredential.tenant_id == actor.tenant.id)
        .order_by(ParserCredential.id)
    )
    member = (
        await db.get(Membership, row.executor_member_id) if row and row.executor_member_id else None
    )
    user = await db.get(User, member.user_id) if member else None
    return KnowledgeDefaultsView(
        version=row.version if row else 0,
        embedding_model_id=row.embedding_model_id if row else None,
        rerank_model_id=row.rerank_model_id if row else None,
        rerank_enabled=row.rerank_enabled if row else False,
        credentials=[CredentialView.model_validate(c) for c in credentials],
        models=options,
        executor_name=user.name if user else None,
    )


@router.put(
    "/defaults", response_model=KnowledgeDefaultsView, summary="设置组织默认模型并授权知识库调用"
)
async def save_defaults(
    body: KnowledgeDefaults, request: Request, db: DB, _: Mutation
) -> KnowledgeDefaultsView:
    actor = await access(request, db, write=True)
    row = await db.get(KnowledgeSettings, actor.tenant.id)
    if body.version != (row.version if row else 0):
        raise HTTPException(409, "默认配置已变化，请刷新")
    selections: tuple[tuple[UUID | None, Literal["embedding", "rerank"]], ...] = (
        (body.embedding_model_id, "embedding"),
        (body.rerank_model_id, "rerank"),
    )
    for ident, kind in selections:
        if ident:
            model = await db.get(CatalogModel, ident)
            config = (
                CatalogInput.model_validate(model.configuration).for_operation(kind)
                if model
                else None
            )
            if (
                not model
                or model.tenant_id != actor.tenant.id
                or model.archived
                or not config
                or not config.access.enabled
            ):
                raise HTTPException(422, "请选择本组织已开放的对应模型")
            if kind == "embedding" and (
                not config.retrieval.dimensions or not config.retrieval.embedding_space
            ):
                raise HTTPException(422, "请先为向量模型填写维度和向量空间")
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
    row.executor_member_id, row.authorized_at = actor.member.id, now()
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
    if len(rows) + sum(key not in existing for key in keys) > 20:
        raise HTTPException(422, "最多保存 20 个解析凭据")
    result = []
    for key in keys:
        row = existing.get(key)
        if row is None:
            row = ParserCredential(
                tenant_id=actor.tenant.id,
                name=f"Key {len(rows) + 1}",
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


@router.put(
    "/credentials/{credential_id}", response_model=CredentialView, summary="启用或停用解析凭据"
)
async def toggle_credential(
    credential_id: UUID, enabled: bool, request: Request, db: DB, _: Mutation
) -> CredentialView:
    actor = await access(request, db, write=True)
    row = await db.get(ParserCredential, credential_id)
    if not row or row.tenant_id != actor.tenant.id:
        raise HTTPException(404, "凭据不存在")
    row.enabled = enabled
    if enabled:
        row.error, row.cooldown_until = "", None
    record(db, actor, "knowledge.credential.update", row.id, row.name)
    await db.commit()
    return CredentialView.model_validate(row)


@router.get("", response_model=KnowledgePage, summary="列出本人有权访问的知识库")
async def bases(
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
) -> KnowledgePage:
    actor = await access(request, db)
    filters = [KnowledgeBase.tenant_id == actor.tenant.id, KnowledgeBase.archived.is_(False)]
    if q:
        filters.append(KnowledgeBase.name.icontains(q, autoescape=True))
    if actor.member.role != "administrator":
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
    "", response_model=KnowledgeView, status_code=201, summary="创建知识库并快照当前默认向量配置"
)
async def create(body: KnowledgeCreate, request: Request, db: DB, _: Mutation) -> KnowledgeView:
    actor = await access(request, db, write=True)
    grants = await validate_scope(db, actor, body)
    row = KnowledgeBase(
        tenant_id=actor.tenant.id,
        **body.model_dump(mode="json", exclude={"department_grants"}),
        department_grants=grants,
        embedding_profile=await embedding_profile(db, actor.tenant.id),
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
    actor = await access(request, db, write=True)
    row = await get_base(db, actor, base_id)
    if row.version != body.version:
        raise HTTPException(409, "知识库已变化，请刷新")
    grants = await validate_scope(db, actor, body)
    for key, value in body.model_dump(
        mode="json", exclude={"version", "department_grants"}
    ).items():
        setattr(row, key, value)
    row.department_grants, row.updated_at = grants, now()
    row.version += 1
    record(db, actor, "knowledge.update", row.id, row.name)
    result = await base_view(db, row, actor)
    await db.commit()
    return result


@router.delete("/{base_id}", status_code=204, summary="归档知识库并立即停止原文和检索访问")
async def archive(base_id: UUID, request: Request, db: DB, _: Mutation) -> Response:
    actor = await access(request, db, write=True)
    row = await get_base(db, actor, base_id)
    row.archived = True
    record(db, actor, "knowledge.archive", row.id, row.name)
    await db.commit()
    return Response(status_code=204)


@router.get(
    "/{base_id}/documents", response_model=list[DocumentView], summary="列出文档及最新处理进度"
)
async def documents(base_id: UUID, request: Request, db: DB) -> list[DocumentView]:
    actor = await access(request, db)
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
    actor = await access(request, db, write=True)
    base = await get_base(db, actor, base_id)
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
    actor = await access(request, db)
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
    view = (await document_view(db, row)).model_dump()
    if generation:
        view.update(
            generation_id=generation.id,
            status=generation.status,
            error=generation.error,
            chunk_count=(
                await db.scalar(
                    select(func.count())
                    .select_from(KnowledgeChunk)
                    .where(KnowledgeChunk.generation_id == ident)
                )
            )
            or 0,
            indexed_count=await db.scalar(
                select(func.count(KnowledgeChunk.vector)).where(
                    KnowledgeChunk.generation_id == ident
                )
            )
            or 0,
        )
    return DocumentDetail(
        **view,
        chunks=[ChunkView.model_validate(c) for c in chunks],
        total_chunks=total or 0,
        can_manage=actor.member.role == "administrator",
        source_url=f"/api/v1/knowledge/{base_id}/documents/{document_id}/source",
    )


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
    actor = await access(request, db, write=True)
    base, row = await get_document(db, actor, base_id, document_id)
    if row.latest_generation_id != body.generation_id:
        raise HTTPException(409, "文档处理版本已变化，请刷新")
    previous = await db.get(KnowledgeGeneration, row.latest_generation_id)
    if previous and previous.lease_until and previous.lease_until > now():
        raise HTTPException(409, "文档正在处理中，请稍后重试")
    if body.use_current_defaults:
        profile = await embedding_profile(db, base.tenant_id)
        if base.embedding_profile and base.embedding_profile != profile:
            raise HTTPException(409, "已有向量空间不能直接更换，请新建知识库后重新导入")
        base.embedding_profile = profile
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
    actor = await access(request, db, write=True)
    base, row = await get_document(db, actor, base_id, document_id)
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
    actor = await access(request, db)
    chunk = await db.get(KnowledgeChunk, chunk_id)
    generation = await db.get(KnowledgeGeneration, chunk.generation_id) if chunk else None
    if not chunk or not generation:
        raise HTTPException(404, "引用不存在")
    base, doc = await get_document(db, actor, base_id, generation.document_id)
    return citation(base, doc, chunk)


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
