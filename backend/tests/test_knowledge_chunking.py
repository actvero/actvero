"""Regression checks for balanced source-preserving structural chunking."""

from collections import defaultdict
from itertools import pairwise

from app.modules.knowledge.parsing import split_blocks, split_parent_child
from app.modules.knowledge.schemas import Chunking


def assert_exact_coverage(blocks, chunks):
    source = {block["block_id"]: block["text"] for block in blocks}
    coverage = defaultdict(list)
    for content, refs in chunks:
        assert content == "\n\n".join(
            source[ref["block_id"]][ref["start"] : ref["end"]] for ref in refs
        )
        for ref in refs:
            assert 0 <= ref["start"] < ref["end"] <= len(source[ref["block_id"]])
            coverage[ref["block_id"]].append((ref["start"], ref["end"]))
    for block_id, text in source.items():
        spans = coverage[block_id]
        assert spans[0][0] == 0 and spans[-1][1] == len(text)
        assert all(left[1] == right[0] for left, right in pairwise(spans))


def test_balances_short_tail_without_breaking_sentences_or_source_offsets():
    text = "这是带有原文定位的完整句子🙂。" * 61
    blocks = [{"block_id": "a", "text": text, "type": "text", "page": 2}]
    chunks = split_blocks(blocks, Chunking(target_chars=300, max_chars=400))
    lengths = [len(content) for content, _ in chunks]
    assert max(lengths) <= 400 and min(lengths) >= 250
    assert max(lengths) - min(lengths) <= 2 * len("这是带有原文定位的完整句子🙂。")
    assert all(content.endswith("。") for content, _ in chunks)
    assert_exact_coverage(blocks, chunks)


def test_keeps_short_heading_with_body_and_preserves_large_table():
    blocks = [
        {"block_id": "h", "type": "title", "text": "章节标题", "page": 1},
        {"block_id": "p", "type": "text", "text": "第一段正文。" * 30, "page": 1},
        {"block_id": "t", "type": "table", "text": "列一 | 列二\n" * 100, "page": 2},
    ]
    chunks = split_blocks(blocks, Chunking(target_chars=200, max_chars=300), hard_limit=2000)
    assert chunks[0][0].startswith("章节标题\n\n第一段正文。")
    assert any(content == blocks[2]["text"] for content, _ in chunks)
    assert_exact_coverage(blocks, chunks)
    limited = split_blocks(blocks, Chunking(target_chars=200, max_chars=300), hard_limit=100)
    assert all(len(content) <= 100 for content, _ in limited)
    assert_exact_coverage(blocks, limited)


def test_long_runs_of_titles_and_unpunctuated_text_stay_bounded():
    blocks = [
        {"block_id": str(i), "type": "title", "text": "标题" * 120, "page": i + 1}
        for i in range(14)
    ]
    blocks.append({"block_id": "body", "type": "text", "text": "资料🙂" * 4000, "page": 15})
    chunks = split_blocks(blocks, Chunking(target_chars=300, max_chars=450))
    assert all(len(content) <= 450 for content, _ in chunks)
    assert_exact_coverage(blocks, chunks)


def test_parent_children_balance_tail_and_cover_all_source_characters():
    blocks = [
        {"block_id": str(i), "type": "text", "text": f"第{i}段中文资料🙂。" * 15, "page": i + 1}
        for i in range(12)
    ]
    groups = split_parent_child(
        blocks,
        Chunking(structure="parent_child", target_chars=1200, max_chars=1800, child_chars=500),
        hard_limit=10000,
    )
    children = [chunk for _, group in groups for chunk in group]
    assert all(250 <= len(content) <= 500 for content, _ in children)
    assert all(len(content) <= 1800 for content, _ in groups)
    assert_exact_coverage(blocks, children)


def test_target_size_changes_long_paragraph_chunk_sizes():
    blocks = [{"block_id": "a", "type": "text", "text": "这是一个完整的句子。" * 700}]
    small = split_blocks(blocks, Chunking(target_chars=600, max_chars=900))
    large = split_blocks(blocks, Chunking(target_chars=1200, max_chars=1800))
    assert len(small) > len(large)
    assert max(len(value) for value, _ in small) <= 900
    assert max(len(value) for value, _ in large) <= 1800
    assert_exact_coverage(blocks, small)
    assert_exact_coverage(blocks, large)


def test_major_sections_do_not_merge_to_fill_target():
    blocks = [
        {"block_id": "toc", "type": "text", "text": "目录内容。" * 140},
        {"block_id": "h1", "type": "title", "text": "第一章 项目说明"},
        {"block_id": "p1", "type": "text", "text": "正文说明。" * 150},
        {"block_id": "h2", "type": "title", "text": "第二章 费用管理"},
        {"block_id": "p2", "type": "text", "text": "费用管理。" * 150},
    ]
    chunks = split_blocks(blocks, Chunking(target_chars=1200, max_chars=1800))
    assert len(chunks) == 3
    assert chunks[1][0].startswith("第一章 项目说明\n\n正文说明。")
    assert chunks[2][0].startswith("第二章 费用管理\n\n费用管理。")
    assert_exact_coverage(blocks, chunks)
