from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.account.service import own_access
from app.modules.departments.access import resolve_grants
from app.modules.integrations.actor import ApplicationActor
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
    KnowledgeFields,
    KnowledgeView,
    RetrievalPolicy,
)
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import CatalogModel
from app.modules.members.models import Membership
from app.modules.members.service import Access, BusinessActor
from app.modules.skills.icons import library_image
from app.modules.skills.schemas import SkillIconSelectionView


async def access(request: Request, db: AsyncSession, *, write: bool = False) -> Access:
    actor = await own_access(request, db, write=write, allow_platform_elevation=False)
    if write and actor.member.role != "administrator":
        raise HTTPException(403, "此操作仅限当前组织管理员")
    return actor


KnowledgeActor = BusinessActor | ApplicationActor


def can_manage(base: KnowledgeBase, actor: KnowledgeActor) -> bool:
    if isinstance(actor, ApplicationActor):
        return base.application_id == actor.application.id and base.tenant_id == actor.tenant.id
    return actor.member.role == "administrator"


def require_manage(base: KnowledgeBase, actor: KnowledgeActor) -> None:
    if not can_manage(base, actor):
        raise HTTPException(403, "应用只能修改自己创建的知识库")


def visible(base: KnowledgeBase, actor: KnowledgeActor) -> bool:
    if isinstance(actor, ApplicationActor):
        return (
            not base.archived
            and base.tenant_id == actor.tenant.id
            and (base.application_id == actor.application.id or base.audience == "organization")
        )
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


async def get_base(
    db: AsyncSession, actor: KnowledgeActor, ident: UUID, *, lock: bool = False
) -> KnowledgeBase:
    query = select(KnowledgeBase).where(
        KnowledgeBase.id == ident, KnowledgeBase.tenant_id == actor.tenant.id
    )
    if lock:
        query = query.with_for_update()
    row = await db.scalar(query.execution_options(populate_existing=True))
    if row is None or not visible(row, actor):
        raise HTTPException(404, "知识库不存在或未获授权")
    return row


async def get_document(
    db: AsyncSession,
    actor: KnowledgeActor,
    base_id: UUID,
    ident: UUID,
    *,
    lock_base: bool = False,
) -> tuple[KnowledgeBase, KnowledgeDocument]:
    base = await get_base(db, actor, base_id, lock=lock_base)
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
    db: AsyncSession, actor: KnowledgeActor, body: KnowledgeFields
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
    return await resolve_embedding(db, tenant_id, settings.embedding_model_id)


async def retrieval_model(
    db: AsyncSession, tenant_id: UUID, model_id: UUID, kind: Literal["embedding", "rerank"]
) -> tuple[CatalogModel, CatalogInput]:
    row = await db.get(CatalogModel, model_id)
    if not row or row.tenant_id != tenant_id or row.archived:
        raise HTTPException(422, "请选择本组织已开放的对应模型")
    config = CatalogInput.model_validate(row.configuration).for_operation(kind)
    if not config or not config.access.enabled:
        raise HTTPException(422, "请选择本组织已开放的对应模型")
    return row, config


async def resolve_embedding(db: AsyncSession, tenant_id: UUID, model_id: UUID) -> dict[str, Any]:
    row, config = await retrieval_model(db, tenant_id, model_id, "embedding")
    if not config.retrieval.embedding_space or not config.retrieval.dimensions:
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


def default_retrieval(settings: KnowledgeSettings | None) -> RetrievalPolicy:
    model = settings.embedding_model_id if settings else None
    return RetrievalPolicy(
        mode="hybrid" if model else "keyword",
        embedding_model_id=model,
        rerank_model_id=settings.rerank_model_id if settings and settings.rerank_enabled else None,
    )


async def effective_retrieval(db: AsyncSession, base: KnowledgeBase) -> RetrievalPolicy:
    if base.retrieval is not None:
        return RetrievalPolicy.model_validate(base.retrieval)
    # Existing bases retain their embedding snapshot and organization reranker.
    settings = await db.get(KnowledgeSettings, base.tenant_id, populate_existing=True)
    model = base.embedding_profile.get("model_id")
    return default_retrieval(settings).model_copy(
        update={
            "mode": "hybrid" if model else "keyword",
            "embedding_model_id": UUID(model) if model else None,
        }
    )


async def base_view(db: AsyncSession, row: KnowledgeBase, actor: KnowledgeActor) -> KnowledgeView:
    icon = SkillIconSelectionView.model_validate(row.icon_selection or {})
    if icon.source == "library":
        try:
            icon.image = library_image(icon.key)
        except ValueError:
            icon = SkillIconSelectionView()
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
            "icon": icon,
            "audience": row.audience,
            "member_ids": row.member_ids,
            "department_grants": row.department_grants,
            "chunking": row.chunking,
            "embedding_profile": row.embedding_profile,
            "retrieval": await effective_retrieval(db, row),
            "version": row.version,
            "document_count": len(documents),
            "status": status,
            "updated_at": row.updated_at,
            "can_manage": can_manage(row, actor),
        }
    )


async def document_view(
    db: AsyncSession, row: KnowledgeDocument, generation_id: UUID | None = None
) -> DocumentView:
    ident = generation_id or row.latest_generation_id
    generation = await db.get(KnowledgeGeneration, ident) if ident else None
    total, indexed = (
        await db.execute(
            select(
                func.count(KnowledgeChunk.id),
                func.count(KnowledgeChunk.vector),
            ).where(KnowledgeChunk.generation_id == ident)
        )
    ).one()
    # Older stopped jobs share the failure workflow; preserve their execution evidence.
    legacy_unknown = generation is not None and generation.status == "uncertain"
    return DocumentView(
        id=row.id,
        filename=row.filename,
        media_type=row.media_type,
        size=row.size,
        created_at=row.created_at,
        generation_id=ident,
        active_generation_id=row.active_generation_id,
        status="failed" if legacy_unknown else generation.status if generation else "queued",
        error="未取得外部服务处理结果，请重试处理"
        if legacy_unknown
        else generation.error
        if generation
        else "",
        chunk_count=total,
        indexed_count=indexed,
        chunk_structure=Chunking.model_validate(generation.chunking).structure
        if generation
        else None,
        character_count=generation.character_count if generation else None,
    )


async def enqueue(
    db: AsyncSession,
    base: KnowledgeBase,
    document: KnowledgeDocument,
    actor: KnowledgeActor,
    config: Chunking | None = None,
) -> KnowledgeGeneration:
    row = KnowledgeGeneration(
        document_id=document.id,
        actor_member_id=actor.member.id if isinstance(actor, BusinessActor) else None,
        actor_integration_key_id=actor.key.id if isinstance(actor, ApplicationActor) else None,
        chunking=(config or Chunking.model_validate(base.chunking)).model_dump(),
        embedding_profile=index_profile(base),
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


def index_profile(base: KnowledgeBase) -> dict[str, Any]:
    if base.retrieval is not None and base.retrieval["mode"] == "keyword":
        return {}
    return dict(base.embedding_profile)


def list_filter(actor: KnowledgeActor) -> Any:
    if isinstance(actor, ApplicationActor):
        return or_(
            KnowledgeBase.audience == "organization",
            KnowledgeBase.application_id == actor.application.id,
        )
    return or_(
        KnowledgeBase.audience == "organization",
        (KnowledgeBase.audience == "selected")
        & or_(
            KnowledgeBase.member_ids.contains([str(actor.member.id)]),
            actor.departments.predicate(KnowledgeBase.department_grants),
        ),
    )
