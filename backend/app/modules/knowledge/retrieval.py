import math
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.modules.knowledge.inference import invoke
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeGeneration,
    KnowledgeSettings,
)
from app.modules.knowledge.parsing import terms
from app.modules.knowledge.schemas import CitationView, RetrievalHit, RetrievalInput, RetrievalView
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.inference_schemas import (
    EmbeddingInput,
    EmbeddingOutput,
    RerankInput,
    RerankOutput,
)
from app.modules.llm.models import CatalogModel
from app.modules.members.service import BusinessActor


def citation(base: KnowledgeBase, doc: KnowledgeDocument, chunk: KnowledgeChunk) -> CitationView:
    return CitationView(
        id=chunk.id,
        base_id=base.id,
        document_id=doc.id,
        generation_id=chunk.generation_id,
        filename=doc.filename,
        content=chunk.content,
        sources=chunk.sources,
        source_url=f"/api/v1/knowledge/{base.id}/documents/{doc.id}/source",
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
    actor: BusinessActor,
    body: RetrievalInput,
) -> RetrievalView:
    count, cells = (
        await db.execute(
            select(
                func.count(KnowledgeChunk.id),
                func.sum(func.jsonb_array_length(KnowledgeChunk.vector)),
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
    rows = (
        await db.execute(
            select(KnowledgeChunk, KnowledgeDocument, KnowledgeGeneration)
            .join(KnowledgeGeneration, KnowledgeGeneration.id == KnowledgeChunk.generation_id)
            .join(
                KnowledgeDocument, KnowledgeDocument.active_generation_id == KnowledgeGeneration.id
            )
            .where(KnowledgeDocument.base_id == base.id, KnowledgeDocument.deleted_at.is_(None))
            .options(undefer(KnowledgeChunk.vector))
            .order_by(KnowledgeChunk.id)
            .limit(10001)
        )
    ).all()
    if len(rows) > 10000:
        raise HTTPException(422, "当前检索版本支持每库最多 10000 个生效切片，请拆分知识库")
    if not rows:
        return RetrievalView(mode="keyword", reranked=False, items=[])
    query_terms = terms(body.query)
    lexical = sorted(
        (
            (i, len(query_terms & terms(c.content)) / max(1, len(query_terms)))
            for i, (c, _, _) in enumerate(rows)
        ),
        key=lambda v: (-v[1], v[0]),
    )
    scores = {i: 1 / (60 + rank) for rank, (i, score) in enumerate(lexical, 1) if score > 0}
    profile = base.embedding_profile
    indexed = [
        (i, c.vector)
        for i, (c, _, g) in enumerate(rows)
        if c.vector and g.embedding_profile == profile
    ]
    mode = "keyword"
    if indexed:
        output = await invoke(
            request,
            db,
            base,
            actor.member.id,
            UUID(profile["model_id"]),
            EmbeddingInput(
                model=profile["slug"], input=body.query, dimensions=profile["dimensions"]
            ),
            purpose="search",
        )
        if not isinstance(output, EmbeddingOutput) or len(output.data) != 1:
            raise HTTPException(502, "查询向量生成失败")
        vector = output.data[0].embedding
        ranked = sorted(
            ((i, cosine(vector, value)) for i, value in indexed), key=lambda v: (-v[1], v[0])
        )
        for rank, (i, score) in enumerate(ranked[:50], 1):
            if score > 0:
                scores[i] = scores.get(i, 0) + 1 / (60 + rank)
        mode = "hybrid"
    selected = sorted(scores, key=lambda i: (-scores[i], i))[:50]
    settings = await db.get(KnowledgeSettings, base.tenant_id)
    reranked = False
    if selected and settings and settings.rerank_enabled and body.rerank is not False:
        model = (
            await db.get(CatalogModel, settings.rerank_model_id)
            if settings.rerank_model_id
            else None
        )
        if not model:
            raise HTTPException(422, "重排序模型不可用，请调整默认配置")
        config = CatalogInput.model_validate(model.configuration)
        output = await invoke(
            request,
            db,
            base,
            actor.member.id,
            model.id,
            RerankInput(
                model=config.slug,
                query=body.query,
                documents=[rows[i][0].content for i in selected],
                top_n=min(body.limit, len(selected)),
            ),
            purpose="search",
        )
        if not isinstance(output, RerankOutput):
            raise HTTPException(502, "重排序未返回有效结果")
        original = selected
        selected = [original[r.index] for r in output.results]
        scores = {original[r.index]: r.relevance_score for r in output.results}
        reranked = True
    return RetrievalView(
        mode=mode,
        reranked=reranked,
        items=[
            RetrievalHit(**citation(base, rows[i][1], rows[i][0]).model_dump(), score=scores[i])
            for i in selected[: body.limit]
        ],
    )
