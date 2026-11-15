"""Original-file previews keep parser coordinates but never substitute parsed text."""

import csv
import io
from typing import Any
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.knowledge.models import KnowledgeChunk, KnowledgeDocument, KnowledgeGeneration
from app.modules.knowledge.schemas import DocumentPreview, OriginalTextRange
from app.modules.knowledge.service import KnowledgeActor, get_document


def original_response(row: KnowledgeDocument) -> Response:
    inline = row.media_type in {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "text/plain",
        "text/csv",
        "text/markdown",
    }
    disposition = "inline" if inline else "attachment"
    return Response(
        row.data,
        media_type=row.media_type,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(row.filename)}",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


async def preview(
    db: AsyncSession,
    actor: KnowledgeActor,
    base_id: UUID,
    document_id: UUID,
    generation_id: UUID | None = None,
    chunk_id: UUID | None = None,
) -> DocumentPreview:
    _, doc = await get_document(db, actor, base_id, document_id)
    ident = generation_id or doc.latest_generation_id
    generation = await db.get(KnowledgeGeneration, ident) if ident else None
    if ident and (not generation or generation.document_id != doc.id):
        raise HTTPException(404, "原文版本不存在")
    chunk = await db.get(KnowledgeChunk, chunk_id) if chunk_id else None
    if chunk_id and (not chunk or chunk.generation_id != ident):
        raise HTTPException(404, "引用不属于此文档版本")
    ranges: list[OriginalTextRange] = []
    if chunk and generation and doc.media_type.startswith("text/"):
        await db.refresh(doc, ["data"])
        await db.refresh(generation, ["blocks"])
        ranges = original_text_ranges(doc.data, doc.media_type, generation.blocks, chunk.sources)
    return DocumentPreview(
        document_id=doc.id,
        generation_id=ident,
        filename=doc.filename,
        media_type=doc.media_type,
        source_url=f"/api/v1/knowledge/{base_id}/documents/{document_id}/source",
        sources=chunk.sources if chunk else [],
        text_ranges=ranges,
        citation_id=chunk.id if chunk else None,
    )


def original_text_ranges(
    data: bytes, media_type: str, blocks: list[dict[str, Any]], sources: list[dict[str, Any]]
) -> list[OriginalTextRange]:
    ranges: list[OriginalTextRange] = []
    if not media_type.startswith("text/"):
        return ranges
    text = data.decode("utf-8-sig")
    if media_type == "text/csv":
        raw = io.StringIO(text, newline="")
        positions = [0]
        for line in raw:
            positions.append(positions[-1] + len(line))
        selected = {s.get("line") for s in sources}
        raw.seek(0)
        reader = csv.reader(raw)
        previous = 0
        for index, _ in enumerate(reader, 1):
            if index in selected:
                ranges.append(
                    OriginalTextRange(start=positions[previous], end=positions[reader.line_num])
                )
            previous = reader.line_num
    else:
        by_id = {b["block_id"]: b for b in blocks}
        lines = text.split("\n")
        positions = [0]
        for line in lines:
            positions.append(positions[-1] + len(line) + 1)
        for source in sources:
            block = by_id.get(source["block_id"])
            if not block or not block.get("line"):
                continue
            line_index = int(block["line"]) - 1
            if not 0 <= line_index < len(lines):
                continue
            # A parser block may trim leading whitespace; anchor within its actual line.
            start = text.find(block["text"], positions[line_index])
            if start < 0 or start >= positions[line_index + 1]:
                continue
            lo, hi = source.get("start", 0), source.get("end", len(block["text"]))
            if 0 <= lo < hi <= len(block["text"]):
                ranges.append(OriginalTextRange(start=start + lo, end=start + hi))
    return ranges
