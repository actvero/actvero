# SPDX-License-Identifier: LGPL-3.0-only
# Adapted from ENGI's _SmartDocumentRagChunkBuilder (engi-one, LGPL-3).
# Source, modifications and full license: licenses/engi-rag-NOTICE.txt and LICENSE.txt.
"""Balance adjacent source ranges while preferring title and paragraph boundaries."""

import math
import re
from itertools import chain
from typing import Any

SKIPPED_TYPES = {"header", "footer", "page_header", "page_footer", "page_number", "discarded"}
TITLE_TYPES = {"title", "doc_title", "paragraph_title"}
SECTION_TITLE = re.compile(
    r"^(?:#{1,2}\s|第[一二三四五六七八九十百零〇0-9]+[篇章部]\s|(?:chapter|part)\s+[0-9ivxlc]+\b)",
    re.IGNORECASE,
)
SENTENCE_END = re.compile(r'[。！？；][”’」』）]*\s*|[.!?;]["\'”’)]*(?:\s+|$)')


def block_ranges(text: str, maximum: int) -> list[tuple[int, int, float]]:
    """Offer sentence ends, with balanced word/character fallbacks for long sentences."""
    result = []
    start = 0
    # Bound the number of candidate boundaries in punctuation-heavy documents.
    minimum_step = max(1, maximum // 32)
    ends = chain((match.end() for match in SENTENCE_END.finditer(text)), [len(text)])
    for end in ends:
        if end == start or (end - start < minimum_step and end < len(text)):
            continue
        while end - start > maximum:
            width = math.ceil((end - start) / math.ceil((end - start) / maximum))
            stop = start + width
            boundary = max(text.rfind(c, start + width // 2, stop) for c in " ，,\n\t")
            if boundary >= 0:
                stop = boundary + 1
            result.append((start, stop, 0.8))
            start = stop
        result.append((start, end, 0.3))
        start = end
    return result


def structural_groups(
    blocks: list[dict[str, Any]], *, target: int, maximum: int, hard_limit: int = 10000
) -> list[list[dict[str, Any]]]:
    """Minimize length imbalance and boundary cost without changing source characters."""
    maximum = min(maximum, hard_limit)
    target = min(target, maximum)
    parts: list[dict[str, Any]] = []
    starts: list[int] = []
    ends: list[int] = []
    penalties: list[float] = []
    sections: list[int] = []
    section_start = 0
    section_has_body = False
    for block_index, block in enumerate(blocks):
        kind = block.get("type", "text")
        text = block["text"]
        if kind in SKIPPED_TYPES or not text.strip():
            continue
        following_text = blocks[block_index + 1]["text"] if block_index + 1 < len(blocks) else ""
        title_context = text + "\n" + following_text[:160]
        major_title = (
            kind in TITLE_TYPES
            and len(text) <= 160
            and (kind == "doc_title" or SECTION_TITLE.match(text))
            and not re.search(r"\.{3}|…|[.．]\s*\d+\s*$", title_context)
        )
        section_size = ends[-1] - starts[section_start] if parts else 0
        if major_title and section_has_body and section_size >= target // 2:
            section_start = len(parts)
            section_has_body = False
        section_has_body = section_has_body or kind not in TITLE_TYPES
        # Tables may exceed the soft maximum, but never the model's hard limit.
        if (kind == "table" and len(text) <= hard_limit) or (
            kind in TITLE_TYPES and len(text) <= maximum
        ):
            ranges = [(0, len(text), 0.15)]
        else:
            ranges = block_ranges(text, maximum)
        origin = block.get("start", 0)
        for left, right, penalty in ranges:
            separator = 2 if parts and parts[-1]["block_id"] != block["block_id"] else 0
            starts.append((ends[-1] if ends else 0) + separator)
            ends.append(starts[-1] + right - left)
            parts.append({**block, "text": text[left:right], "start": origin + left})
            penalties.append(penalty if right < len(text) else 0.15)
            sections.append(section_start)

    count = len(parts)
    costs = [0.0] + [float("inf")] * count
    previous = [0] * (count + 1)
    for end in range(1, count + 1):
        last = parts[end - 1]
        if end < count:
            following = parts[end]
            penalty = 0.0 if following.get("type") in TITLE_TYPES else penalties[end - 1]
            if last.get("type") in TITLE_TYPES and ends[end] - starts[end - 1] <= maximum:
                # A finite penalty also handles runs of headings larger than the cap.
                penalty = 2.0
        else:
            penalty = 0.0
        for start in range(end - 1, sections[end - 1] - 1, -1):
            size = ends[end - 1] - starts[start]
            if size > maximum and start < end - 1:
                break
            ratio = size / target
            cost = costs[start] + (ratio - 1) ** 2 + 4 * max(0, 0.5 - ratio) ** 2
            cost += 0.1 + penalty
            if cost < costs[end]:
                costs[end] = cost
                previous[end] = start

    groups = []
    end = count
    while end:
        start = previous[end]
        group: list[dict[str, Any]] = []
        for part in parts[start:end]:
            if group and group[-1]["block_id"] == part["block_id"]:
                group[-1]["text"] += part["text"]
            else:
                group.append(dict(part))
        groups.append(group)
        end = start
    return list(reversed(groups))
