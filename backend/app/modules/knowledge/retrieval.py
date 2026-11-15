import math
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.modules.integrations.actor import ApplicationActor
from app.modules.knowledge.inference import invoke
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeGeneration,
    KnowledgeParentChunk,
)
from app.modules.knowledge.parsing import terms
from app.modules.knowledge.schemas import (
    CitationView,
    ParentContext,
    RetrievalHit,
    RetrievalInput,
    RetrievalView,
)
from app.modules.knowledge.service import KnowledgeActor, effective_retrieval, retrieval_model
from app.modules.llm.inference_schemas import (
    EmbeddingInput,
    EmbeddingOutput,
    RerankInput,
    RerankOutput,
)
from app.modules.members.service import BusinessActor


def citation(
    base: KnowledgeBase, doc: KnowledgeDocument, chunk: KnowledgeChunk, *, application: bool = False
) -> CitationView:
    return CitationView(
        id=chunk.id,
        base_id=base.id,
        document_id=doc.id,
        generation_id=chunk.generation_id,
        filename=doc.filename,
        content=chunk.content,
        sources=chunk.sources,
        source_url=(
            f"/api/integrations/v1/knowledge/bases/{base.id}/documents/{doc.id}/source"
            if application
            else f"/api/v1/knowledge/{base.id}/documents/{doc.id}/source"
        ),
    )


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return -1
    divisor = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / divisor if divisor else 0


async def search(
    request: Request,
    db: AsyncSession,
    base: KnowledgeBase,
    actor: KnowledgeActor,
    body: RetrievalInput,
) -> RetrievalView:
    policy = await effective_retrieval(db, base)
    use_vectors = policy.mode != "keyword"
    count, cells = (
        await db.execute(
            select(
                func.count(KnowledgeChunk.id),
                func.sum(func.jsonb_array_length(KnowledgeChunk.vector))
                if use_vectors
                else literal(0),
            )
            .join(KnowledgeGeneration, KnowledgeGeneration.id == KnowledgeChunk.generation_id)
            .join(
                KnowledgeDocument, KnowledgeDocument.active_generation_id == KnowledgeGeneration.id
            )
            .where(KnowledgeDocument.base_id == base.id, KnowledgeDocument.deleted_at.is_(None))
        )
    ).one()
    if count > 10000 or (cells or 0) > 2000000:
        raise HTTPException(422, "当前知识库超出精确检索容量，请拆分资料库或升级索引存储")
    query = (
        select(KnowledgeChunk, KnowledgeDocument, KnowledgeGeneration)
        .join(KnowledgeGeneration, KnowledgeGeneration.id == KnowledgeChunk.generation_id)
        .join(KnowledgeDocument, KnowledgeDocument.active_generation_id == KnowledgeGeneration.id)
        .where(KnowledgeDocument.base_id == base.id, KnowledgeDocument.deleted_at.is_(None))
        .order_by(KnowledgeChunk.id)
        .limit(10001)
    )
    if use_vectors:
        query = query.options(undefer(KnowledgeChunk.vector))
    rows = (await db.execute(query)).all()
    if len(rows) > 10000:
        raise HTTPException(422, "当前检索版本支持每库最多 10000 个生效切片，请拆分知识库")
    profile = base.embedding_profile
    indexed = [
        (i, c.vector)
        for i, (c, _, g) in enumerate(rows)
        if use_vectors and c.vector and g.embedding_profile == profile
    ]
    mode = "keyword" if policy.mode == "hybrid" and not indexed else policy.mode
    scores: dict[int, float] = {}
    if mode != "vector":
        query_terms = terms(body.query)
        lexical = sorted(
            ((i, len(query_terms & terms(c.content))) for i, (c, _, _) in enumerate(rows)),
            key=lambda v: (-v[1], v[0]),
        )
        weight = (100 - policy.vector_weight) / 50 if mode == "hybrid" else 1
        scores = {
            i: weight / (60 + rank) for rank, (i, score) in enumerate(lexical, 1) if score > 0
        }
    if indexed:
        output = await invoke(
            request,
            db,
            base,
            actor.member.id if isinstance(actor, BusinessActor) else None,
            UUID(profile["model_id"]),
            EmbeddingInput(
                model=profile["slug"], input=body.query, dimensions=profile["dimensions"]
            ),
            purpose="search",
            application_key_id=actor.key.id if isinstance(actor, ApplicationActor) else None,
        )
        if not isinstance(output, EmbeddingOutput) or len(output.data) != 1:
            raise HTTPException(502, "查询向量生成失败")
        vector = output.data[0].embedding
        if len(vector) != profile["dimensions"]:
            raise HTTPException(502, "查询向量维度与索引不一致")
        ranked = sorted(
            ((i, cosine(vector, value)) for i, value in indexed), key=lambda v: (-v[1], v[0])
        )
        if mode == "vector":
            scores = dict(ranked[:50])
        else:
            weight = policy.vector_weight / 50
            for rank, (i, score) in enumerate(ranked[:50], 1):
                if score > 0:
                    scores[i] = scores.get(i, 0) + weight / (60 + rank)
    selected = sorted(scores, key=lambda i: (-scores[i], i))[:50]
    context_ids = {rows[i][0].parent_id or rows[i][0].id for i in selected}
    reranked = False
    if selected and policy.rerank_model_id and body.rerank is not False:
        model, config = await retrieval_model(db, base.tenant_id, policy.rerank_model_id, "rerank")
        output = await invoke(
            request,
            db,
            base,
            actor.member.id if isinstance(actor, BusinessActor) else None,
            model.id,
            RerankInput(
                model=config.slug,
                query=body.query,
                documents=[rows[i][0].content for i in selected],
                top_n=(
                    len(selected)
                    if len(context_ids) < len(selected)
                    else min(body.limit, len(selected))
                ),
            ),
            purpose="search",
            application_key_id=actor.key.id if isinstance(actor, ApplicationActor) else None,
        )
        if not isinstance(output, RerankOutput):
            raise HTTPException(502, "重排序未返回有效结果")
        original = selected
        selected = [original[r.index] for r in output.results]
        scores = {original[r.index]: r.relevance_score for r in output.results}
        reranked = True
    unique: dict[UUID, int] = {}
    for i in selected:
        chunk = rows[i][0]
        unique.setdefault(chunk.parent_id or chunk.id, i)
        if len(unique) == body.limit:
            break
    parent_ids = {rows[i][0].parent_id for i in unique.values()} - {None}
    parents = (
        {
            (parent.generation_id, parent.id): ParentContext(id=parent.id, content=parent.content)
            for parent in await db.scalars(
                select(KnowledgeParentChunk).where(KnowledgeParentChunk.id.in_(parent_ids))
            )
        }
        if parent_ids
        else {}
    )
    items = []
    for i in unique.values():
        chunk, doc, _ = rows[i]
        parent = parents.get((chunk.generation_id, chunk.parent_id)) if chunk.parent_id else None
        items.append(
            RetrievalHit(
                **citation(
                    base, doc, chunk, application=isinstance(actor, ApplicationActor)
                ).model_dump(),
                score=scores[i],
                parent_context=parent,
            )
        )
    return RetrievalView(mode=mode, reranked=reranked, items=items)
