"""Application knowledge APIs share console operations and index workers."""

from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.modules.auth.service import DB, now
from app.modules.integrations import service
from app.modules.integrations.actor import ApplicationActor
from app.modules.knowledge import router as knowledge
from app.modules.knowledge.models import KnowledgeSettings
from app.modules.knowledge.preview import original_response
from app.modules.knowledge.reader import issue
from app.modules.knowledge.retrieval import search
from app.modules.knowledge.schemas import (
    ChunkPreviewInput,
    ChunkPreviewView,
    CitationView,
    DocumentDetail,
    DocumentView,
    KnowledgeCreate,
    KnowledgePage,
    KnowledgeUpdate,
    KnowledgeView,
    ModelOption,
    ReaderSessionInput,
    ReaderSessionView,
    RebuildInput,
    RetrievalInput,
    RetrievalPolicy,
    RetrievalView,
)
from app.modules.knowledge.service import base_view, default_retrieval, get_base, get_document
from app.modules.tenants.models import Tenant

router = APIRouter(prefix="/knowledge/bases", tags=["application-knowledge"])


async def access(request: Request, db: DB, *, write: bool = False) -> ApplicationActor:
    actor = await service.authorize(request, db, "knowledge_write" if write else "knowledge")
    if write:
        await db.scalar(select(Tenant.id).where(Tenant.id == actor.tenant.id).with_for_update())
        return await service.authorize(request, db, "knowledge_write")
    return actor


async def used(db: DB, actor: ApplicationActor) -> None:
    actor.key.last_used_at = now()
    await db.commit()


class ApplicationKnowledgeDefaults(BaseModel):
    version: int
    retrieval: RetrievalPolicy
    models: list[ModelOption]


@router.get(
    "/defaults",
    response_model=ApplicationKnowledgeDefaults,
    summary="读取组织默认检索配置和模型选项",
)
async def defaults(request: Request, db: DB) -> ApplicationKnowledgeDefaults:
    actor = await access(request, db)
    settings = await db.get(KnowledgeSettings, actor.tenant.id)
    return ApplicationKnowledgeDefaults(
        version=settings.version if settings else 0,
        retrieval=default_retrieval(settings),
        models=await knowledge.model_options(db, actor.tenant.id),
    )


@router.get("", response_model=KnowledgePage, summary="列出应用自建和组织全员可用的知识库")
async def bases(
    request: Request,
    db: DB,
    q: str = Query("", max_length=100),
    page: int = Query(1, ge=1),
) -> KnowledgePage:
    actor = await access(request, db)
    result = await knowledge.list_bases(db, actor, q, page)
    await used(db, actor)
    return result


@router.post(
    "", response_model=KnowledgeView, status_code=201, summary="按 creation_id 幂等创建知识库"
)
async def create(
    body: KnowledgeCreate, creation_id: UUID, request: Request, db: DB
) -> KnowledgeView:
    return await knowledge.create_base(db, await access(request, db, write=True), body, creation_id)


@router.get("/{base_id}", response_model=KnowledgeView, summary="读取知识库配置与处理状态")
async def detail(base_id: UUID, request: Request, db: DB) -> KnowledgeView:
    actor = await access(request, db)
    return await base_view(db, await get_base(db, actor, base_id), actor)


@router.put("/{base_id}", response_model=KnowledgeView, summary="按版本更新应用自建知识库")
async def update(base_id: UUID, body: KnowledgeUpdate, request: Request, db: DB) -> KnowledgeView:
    return await knowledge.update_base(db, await access(request, db, write=True), base_id, body)


@router.delete("/{base_id}", status_code=204, summary="归档应用自建知识库")
async def archive(base_id: UUID, request: Request, db: DB) -> Response:
    return await knowledge.archive_base(db, await access(request, db, write=True), base_id)


@router.get("/{base_id}/documents", response_model=list[DocumentView], summary="查询文档和处理进度")
async def documents(base_id: UUID, request: Request, db: DB) -> list[DocumentView]:
    return await knowledge.list_documents(db, await access(request, db), base_id)


@router.post(
    "/{base_id}/documents",
    response_model=DocumentView,
    status_code=201,
    summary="幂等上传文档原件并排队处理",
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
    base_id: UUID,
    upload_id: UUID,
    filename: str,
    request: Request,
    db: DB,
) -> DocumentView:
    actor = await service.authorize(request, db, "knowledge_write")
    return await knowledge.upload_document(db, actor, base_id, upload_id, filename, request)


@router.get(
    "/{base_id}/documents/{document_id}",
    response_model=DocumentDetail,
    summary="读取文档状态、处理版本与分页切片",
)
async def document(
    base_id: UUID,
    document_id: UUID,
    request: Request,
    db: DB,
    generation_id: UUID | None = None,
    page: int = Query(1, ge=1),
    q: str = Query("", max_length=200),
) -> DocumentDetail:
    return await knowledge.document_detail(
        db, await access(request, db), base_id, document_id, generation_id, page, q
    )


@router.get(
    "/{base_id}/documents/{document_id}/source",
    response_class=Response,
    summary="读取文档原件",
    responses={
        200: {
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            }
        }
    },
)
async def source(base_id: UUID, document_id: UUID, request: Request, db: DB) -> Response:
    _, row = await get_document(db, await access(request, db), base_id, document_id)
    await db.refresh(row, ["data"])
    return original_response(row)


@router.post(
    "/{base_id}/documents/{document_id}/chunk-preview",
    response_model=ChunkPreviewView,
    summary="试算应用自建库的切片，保留原文位置",
)
async def preview_chunks(
    base_id: UUID,
    document_id: UUID,
    body: ChunkPreviewInput,
    request: Request,
    response: Response,
    db: DB,
) -> ChunkPreviewView:
    actor = await service.authorize(request, db, "knowledge_write")
    return await knowledge.preview_document_chunks(db, actor, base_id, document_id, body, response)


@router.post(
    "/{base_id}/documents/{document_id}/rebuild",
    response_model=DocumentView,
    summary="用新切片参数重新处理，完成前保留上一版索引",
)
async def rebuild(
    base_id: UUID,
    document_id: UUID,
    body: RebuildInput,
    request: Request,
    db: DB,
) -> DocumentView:
    return await knowledge.rebuild_document(
        db, await access(request, db, write=True), base_id, document_id, body
    )


@router.delete(
    "/{base_id}/documents/{document_id}",
    status_code=204,
    summary="删除文档并撤销其引用",
)
async def remove(base_id: UUID, document_id: UUID, request: Request, db: DB) -> Response:
    return await knowledge.remove_document(
        db, await access(request, db, write=True), base_id, document_id
    )


@router.post("/{base_id}/search", response_model=RetrievalView, summary="检索知识库并返回原文引用")
async def retrieve(base_id: UUID, body: RetrievalInput, request: Request, db: DB) -> RetrievalView:
    actor = await access(request, db)
    base = await get_base(db, actor, base_id)
    result = await search(request, db, base, actor, body)
    await access(request, db)
    return result


@router.get(
    "/{base_id}/citations/{chunk_id}", response_model=CitationView, summary="读取引用及原文位置"
)
async def reference(base_id: UUID, chunk_id: UUID, request: Request, db: DB) -> CitationView:
    return await knowledge.citation_detail(db, await access(request, db), base_id, chunk_id)


@router.post(
    "/{base_id}/citations/{chunk_id}/reader-session",
    response_model=ReaderSessionView,
    summary="签发绑定原文和宿主来源的短期阅读凭证",
)
async def reader(
    base_id: UUID,
    chunk_id: UUID,
    body: ReaderSessionInput,
    request: Request,
    db: DB,
) -> ReaderSessionView:
    return await issue(
        request, db, await access(request, db), base_id, chunk_id, body.parent_origin
    )
