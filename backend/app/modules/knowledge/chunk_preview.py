"""Read-only chunk experiments using the indexing worker's splitter and source anchors."""

import hashlib
import json
from typing import Any
from uuid import UUID

from app.modules.knowledge.parsing import chunk_limit, split_blocks, split_parent_child
from app.modules.knowledge.preview import original_text_ranges
from app.modules.knowledge.schemas import (
    Chunking,
    ChunkPreviewInput,
    ChunkPreviewItem,
    ChunkPreviewView,
    SourceLocation,
)


def preview_token(generation: UUID, config: Chunking, profile: dict[str, Any]) -> str:
    payload = [str(generation), config.model_dump(), profile]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def build_preview(
    body: ChunkPreviewInput,
    blocks: list[dict[str, Any]],
    profile: dict[str, Any],
    data: bytes,
    media_type: str,
) -> ChunkPreviewView:
    limit = chunk_limit(profile)
    items: list[ChunkPreviewItem] = []
    parents = 0
    if body.chunking.structure == "parent_child":
        for text, children in split_parent_child(blocks, body.chunking, hard_limit=limit):
            parents += 1
            for content, sources in children:
                items.append(
                    ChunkPreviewItem(
                        sequence=len(items) + 1,
                        content=content,
                        sources=[SourceLocation.model_validate(s) for s in sources],
                        parent_sequence=parents,
                        parent_content=text,
                    )
                )
    else:
        items = [
            ChunkPreviewItem(
                sequence=i + 1,
                content=text,
                sources=[SourceLocation.model_validate(s) for s in sources],
            )
            for i, (text, sources) in enumerate(
                split_blocks(blocks, body.chunking, hard_limit=limit)
            )
        ]
    lengths = [len(item.content) for item in items]
    matching = [item for item in items if body.query.casefold() in item.content.casefold()]
    page = matching[(body.page - 1) * 50 : body.page * 50]
    for item in page:
        item.text_ranges = original_text_ranges(
            data, media_type, blocks, [source.model_dump() for source in item.sources]
        )
    return ChunkPreviewView(
        generation_id=body.generation_id,
        chunking=body.chunking,
        preview_token=preview_token(body.generation_id, body.chunking, profile),
        chunks=page,
        total_chunks=len(items),
        filtered_total=len(matching),
        parent_count=parents,
        average_chars=round(sum(lengths) / len(lengths)) if lengths else 0,
        shortest_chars=min(lengths, default=0),
        longest_chars=max(lengths, default=0),
        model_limit=limit,
    )
