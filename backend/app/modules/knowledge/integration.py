"""Server-to-server knowledge APIs, with explicitly scoped personal access keys."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from app.modules.access_keys import service as keys
from app.modules.access_keys.router import bearer
from app.modules.auth.service import DB, now
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeGeneration
from app.modules.knowledge.reader import issue
from app.modules.knowledge.retrieval import citation, search
from app.modules.knowledge.schemas import (
    CitationView,
    KnowledgePage,
    ReaderSessionInput,
    ReaderSessionView,
    RetrievalInput,
    RetrievalView,
)
from app.modules.knowledge.service import base_view, get_base, get_document, visible

router = APIRouter(
    prefix="/api/knowledge/v1", tags=["knowledge-integration"], dependencies=[Depends(bearer)]
)


async def access(
    request: Request, db: DB, base_id: UUID | None = None, action: str = "read"
) -> keys.KeyActor:
    actor = await keys.authorize(request, db, "knowledge", base_id, action)
    actor.key.last_used_at = now()
    await db.commit()
    return actor


@router.get(
    "/bases", response_model=KnowledgePage, summary="列出密钥显式授权且当前成员可访问的知识库"
)
async def bases(request: Request, db: DB, page: int = Query(1, ge=1)) -> KnowledgePage:
    actor = await access(request, db)
    rows = await db.scalars(
        select(KnowledgeBase)
        .where(KnowledgeBase.tenant_id == actor.tenant.id, KnowledgeBase.archived.is_(False))
        .order_by(KnowledgeBase.name, KnowledgeBase.id)
    )
    allowed = [
        b for b in rows if keys.permits(actor, "knowledge", b.id, "read") and visible(b, actor)
    ]
    return KnowledgePage(
        items=[await base_view(db, b, actor) for b in allowed[(page - 1) * 20 : page * 20]],
        total=len(allowed),
    )


@router.post(
    "/bases/{base_id}/search",
    response_model=RetrievalView,
    summary="检索知识库；需要 invoke 授权并沿用组织模型计费",
)
async def retrieve(base_id: UUID, body: RetrievalInput, request: Request, db: DB) -> RetrievalView:
    actor = await access(request, db, base_id, "invoke")
    base = await get_base(db, actor, base_id)
    return await search(request, db, base, actor, body)


@router.get(
    "/bases/{base_id}/citations/{chunk_id}",
    response_model=CitationView,
    summary="读取引用摘要，供宿主渲染角标或悬浮卡片",
)
async def reference(base_id: UUID, chunk_id: UUID, request: Request, db: DB) -> CitationView:
    actor = await access(request, db, base_id)
    chunk = await db.get(KnowledgeChunk, chunk_id)
    generation = await db.get(KnowledgeGeneration, chunk.generation_id) if chunk else None
    if not chunk or not generation:
        raise HTTPException(404, "引用不存在")
    base, doc = await get_document(db, actor, base_id, generation.document_id)
    return citation(base, doc, chunk)


@router.post(
    "/bases/{base_id}/citations/{chunk_id}/reader-session",
    response_model=ReaderSessionView,
    summary="由宿主服务签发短期原文阅读凭证；长期 API Key 不得发送到浏览器",
)
async def reader_session(
    base_id: UUID, chunk_id: UUID, body: ReaderSessionInput, request: Request, db: DB
) -> ReaderSessionView:
    actor = await access(request, db, base_id)
    return await issue(request, db, actor, base_id, chunk_id, body.parent_origin)
