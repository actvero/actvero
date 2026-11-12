from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.account.service import own_access
from app.modules.departments.access import resolve_grants
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeGeneration,
    KnowledgeSettings,
)
from app.modules.knowledge.schemas import (
    Chunking,
    DocumentView,
    KnowledgeCreate,
    KnowledgeView,
)
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import CatalogModel
from app.modules.members.models import Membership
from app.modules.members.service import Access, BusinessActor


async def access(request: Request, db: AsyncSession, *, write: bool = False) -> Access:
    actor = await own_access(request, db, write=write, allow_platform_elevation=False)
    if write and actor.member.role != "administrator":
        raise HTTPException(403, "此操作仅限当前组织管理员")
    return actor


def visible(base: KnowledgeBase, actor: BusinessActor) -> bool:
    return (
        not base.archived
        and base.tenant_id == actor.tenant.id
        and (
            actor.member.role == "administrator"
            or base.audience == "organization"
            or base.audience == "selected"
            and (
                str(actor.member.id) in base.member_ids
                or actor.departments.matches(base.department_grants)
            )
        )
    )


async def get_base(db: AsyncSession, actor: BusinessActor, ident: UUID) -> KnowledgeBase:
    row = await db.scalar(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.id == ident,
            KnowledgeBase.tenant_id == actor.tenant.id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None or not visible(row, actor):
        raise HTTPException(404, "知识库不存在或未获授权")
    return row


async def get_document(
    db: AsyncSession,
    actor: BusinessActor,
    base_id: UUID,
    ident: UUID,
) -> tuple[KnowledgeBase, KnowledgeDocument]:
    base = await get_base(db, actor, base_id)
    row = await db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == ident,
            KnowledgeDocument.base_id == base.id,
            KnowledgeDocument.deleted_at.is_(None),
        )
    )
    if not row:
        raise HTTPException(404, "文档不存在或已删除")
    return base, row


async def validate_scope(
    db: AsyncSession, actor: Access, body: KnowledgeCreate
) -> list[dict[str, Any]]:
    grants = await resolve_grants(
        db, actor.tenant.id, body.audience, body.member_ids, body.department_grants
    )
    if body.member_ids:
        members = set(
            await db.scalars(
                select(Membership.id).where(
                    Membership.tenant_id == actor.tenant.id,
                    Membership.status == "active",
                    Membership.id.in_(body.member_ids),
                )
            )
        )
        if members != set(body.member_ids) or body.audience != "selected":
            raise HTTPException(422, "请选择当前组织的有效授权成员")
    return grants


async def embedding_profile(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    settings = await db.get(KnowledgeSettings, tenant_id)
    if not settings or not settings.embedding_model_id:
        return {}
    row = await db.get(CatalogModel, settings.embedding_model_id)
    if not row or row.tenant_id != tenant_id or row.archived:
        raise HTTPException(422, "默认向量模型不可用，请调整知识库默认配置")
    config = CatalogInput.model_validate(row.configuration).for_operation("embedding")
    if (
        not config
        or not config.access.enabled
        or not config.retrieval.embedding_space
        or not config.retrieval.dimensions
    ):
        raise HTTPException(422, "向量模型须已开放，并配置维度和向量空间")
    return {
        "model_id": str(row.id),
        "slug": config.slug,
        "dimensions": config.retrieval.dimensions,
        "embedding_space": config.retrieval.embedding_space,
        "max_input_characters": config.retrieval.max_input_characters,
        "context_window": config.context_window,
        "model_version": row.version,
        "max_batch_size": config.retrieval.max_batch_size,
    }


async def base_view(db: AsyncSession, row: KnowledgeBase, actor: BusinessActor) -> KnowledgeView:
    documents = list(
        await db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.base_id == row.id,
                KnowledgeDocument.deleted_at.is_(None),
            )
        )
    )
    generations = (
        list(
            await db.scalars(
                select(KnowledgeGeneration).where(
                    KnowledgeGeneration.id.in_([d.latest_generation_id for d in documents]),
                )
            )
        )
        if documents
        else []
    )
    states = {g.status for g in generations}
    status = (
        "empty"
        if not documents
        else "attention"
        if states & {"failed", "uncertain"}
        else "processing"
        if states & {"queued", "parsing", "chunking", "indexing", "waiting"}
        else "unconfigured"
        if "unconfigured" in states
        else "ready"
    )
    return KnowledgeView.model_validate(
        {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "audience": row.audience,
            "member_ids": row.member_ids,
            "department_grants": row.department_grants,
            "chunking": row.chunking,
            "embedding_profile": row.embedding_profile,
            "version": row.version,
            "document_count": len(documents),
            "status": status,
            "updated_at": row.updated_at,
            "can_manage": actor.member.role == "administrator",
        }
    )


async def document_view(db: AsyncSession, row: KnowledgeDocument) -> DocumentView:
    generation = (
        await db.get(KnowledgeGeneration, row.latest_generation_id)
        if row.latest_generation_id
        else None
    )
    total, indexed = (
        await db.execute(
            select(
                func.count(KnowledgeChunk.id),
                func.count(KnowledgeChunk.vector),
            ).where(KnowledgeChunk.generation_id == row.latest_generation_id)
        )
    ).one()
    return DocumentView(
        id=row.id,
        filename=row.filename,
        media_type=row.media_type,
        size=row.size,
        created_at=row.created_at,
        generation_id=row.latest_generation_id,
        active_generation_id=row.active_generation_id,
        status=generation.status if generation else "queued",
        error=generation.error if generation else "",
        chunk_count=total,
        indexed_count=indexed,
    )


async def enqueue(
    db: AsyncSession,
    base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: BusinessActor,
    config: Chunking | None = None,
) -> KnowledgeGeneration:
    row = KnowledgeGeneration(
        document_id=document.id,
        actor_member_id=actor.member.id,
        chunking=(config or Chunking.model_validate(base.chunking)).model_dump(),
        embedding_profile=dict(base.embedding_profile),
    )
    previous = (
        await db.get(KnowledgeGeneration, document.latest_generation_id)
        if document.latest_generation_id
        else None
    )
    if previous:
        await db.refresh(previous, ["blocks", "raw_parse"])
        if previous.blocks:
            row.blocks = previous.blocks
            row.raw_parse = previous.raw_parse
    db.add(row)
    await db.flush()
    document.latest_generation_id = row.id
    return row


def list_filter(actor: BusinessActor) -> Any:
    return or_(
        KnowledgeBase.audience == "organization",
        (KnowledgeBase.audience == "selected")
        & or_(
            KnowledgeBase.member_ids.contains([str(actor.member.id)]),
            actor.departments.predicate(KnowledgeBase.department_grants),
        ),
    )
