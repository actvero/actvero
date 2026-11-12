# SPDX-License-Identifier: LGPL-3.0-only
# Adapted from ENGI's _SmartDocumentRagChunkBuilder (engi-one, LGPL-3).
# Source, modifications and full license: licenses/engi-rag-NOTICE.txt and LICENSE.txt.
"""Structural grouping, independent of Odoo and of the embedding input limit."""

from typing import Any

SKIPPED_TYPES = {"header", "footer", "page_header", "page_footer", "page_number", "discarded"}
TITLE_TYPES = {"title", "doc_title", "paragraph_title"}


def structural_groups(
    blocks: list[dict[str, Any]], *, target: int, maximum: int
) -> list[list[dict[str, Any]]]:
    """Keep original blocks whole; the caller enforces the model's hard limit."""
    minimum = target // 4
    title_boundary = max(minimum, target * 3 // 4)
    result: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    has_body = False

    def flush() -> None:
        nonlocal current, size, has_body
        if current:
            result.append(current)
        current, size, has_body = [], 0, False

    for block in blocks:
        kind = block.get("type", "text")
        if kind in SKIPPED_TYPES or not block["text"].strip():
            continue
        length = len(block["text"])
        exceeds = size + (2 if current else 0) + length > maximum
        title = kind in TITLE_TYPES
        if current:
            if title:
                if size >= title_boundary or (exceeds and size >= minimum):
                    flush()
            elif exceeds and size >= minimum and has_body:
                flush()
        size += length + (2 if current else 0)
        current.append(block)
        has_body = has_body or not title
        if (len(current) == 1 and length >= maximum) or (kind == "table" and size >= target):
            flush()
    flush()
    return result
