"""Preview is read-only, scoped, source-preserving and equivalent to applied indexing."""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from test_identity_access import env as identity_env
from test_knowledge_reader import document

from app.modules.knowledge.chunk_preview import build_preview
from app.modules.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeGeneration
from app.modules.knowledge.parsing import local_parse
from app.modules.knowledge.schemas import Chunking, ChunkPreviewInput
from app.modules.knowledge.worker import tick

env = identity_env


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["smart", "normal", "parent_child"])
async def test_preview_matches_applied_chunks_and_original_anchors(env, mode):
    admin = await env.client()
    text = "# 指南\n\n" + "\n\n".join(
        f"第{i}段。" + "这是保留原文位置的完整句子😀。" * 24 for i in range(12)
    )
    _, doc, path = await document(env, admin, text=text)
    path += f"/documents/{doc['id']}"
    config = Chunking(
        mode="normal" if mode == "normal" else "smart",
        structure="parent_child" if mode == "parent_child" else "general",
        target_chars=500,
        max_chars=750,
        child_chars=300,
        overlap_chars=50,
    ).model_dump()
    request = {"generation_id": doc["generation_id"], "chunking": config}
    async with env.sessions() as db:
        before = await db.scalar(select(func.count()).select_from(KnowledgeGeneration))
        before_chunks = await db.scalar(select(func.count()).select_from(KnowledgeChunk))
    response = await admin.api.post(path + "/chunk-preview", json=request)
    assert response.status_code == 200, response.text
    assert "no-store" in response.headers["cache-control"]
    preview = response.json()
    async with env.sessions() as db:
        assert before == await db.scalar(select(func.count()).select_from(KnowledgeGeneration))
        assert before_chunks == await db.scalar(select(func.count()).select_from(KnowledgeChunk))
    assert preview["chunking"] == config
    assert preview["total_chunks"] > 1
    for chunk in preview["chunks"]:
        assert (
            "\n\n".join(text[r["start"] : r["end"]] for r in chunk["text_ranges"])
            == chunk["content"]
        )
    bad = await admin.api.post(
        path + "/rebuild",
        json={
            **request,
            "chunking": {**config, "max_chars": 800},
            "preview_token": preview["preview_token"],
        },
    )
    assert bad.status_code == 409
    applied = await admin.api.post(
        path + "/rebuild",
        json={
            **request,
            "preview_token": preview["preview_token"],
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["active_generation_id"] == doc["active_generation_id"]
    for _ in range(5):
        await tick(env.app)
    detail = (await admin.api.get(path)).json()
    assert detail["generation_id"] != doc["generation_id"]
    assert detail["chunking"] == config
    assert detail["total_chunks"] == preview["total_chunks"]
    assert [(c["content"], c["sources"]) for c in detail["chunks"]] == [
        (c["content"], c["sources"]) for c in preview["chunks"]
    ]
    assert (await admin.api.post(path + "/chunk-preview", json=request)).status_code == 409


@pytest.mark.asyncio
async def test_preview_permission_generation_and_index_profile_guard(env):
    admin = await env.client()
    base, doc, path = await document(env, admin)
    path += f"/documents/{doc['id']}"
    body = {"generation_id": doc["generation_id"], "chunking": {}}
    member = await env.client("member", tenant=admin.tenant)
    assert (await member.api.post(path + "/chunk-preview", json=body)).status_code == 403
    outsider = await env.client(joined=False)
    assert (await outsider.api.post(path + "/chunk-preview", json=body)).status_code == 403
    _, other, _ = await document(env, admin)
    assert (
        await admin.api.post(
            path + "/chunk-preview",
            json={
                **body,
                "generation_id": other["generation_id"],
            },
        )
    ).status_code == 404
    assert (
        await admin.api.post(
            path + "/chunk-preview",
            json={
                **body,
                "chunking": {"target_chars": 1200, "max_chars": 100},
            },
        )
    ).status_code == 422
    result = (await admin.api.post(path + "/chunk-preview", json=body)).json()
    async with env.sessions() as db:
        row = await db.get(KnowledgeBase, UUID(base["id"]))
        row.embedding_profile = {"max_input_characters": 200}
        await db.commit()
    assert (
        await admin.api.post(
            path + "/rebuild",
            json={
                **body,
                "preview_token": result["preview_token"],
            },
        )
    ).status_code == 409


def test_preview_model_limit_pagination_and_search():
    raw = ("这是较长文档中的完整句子😀。" * 2000).encode()
    blocks = local_parse("manual.txt", raw)
    request = ChunkPreviewInput(generation_id=uuid4(), chunking=Chunking())
    result = build_preview(request, blocks, {"max_input_characters": 200}, raw, "text/plain")
    assert result.total_chunks > 50 and len(result.chunks) == 50
    assert result.longest_chars <= 200 and result.model_limit == 200
    second = build_preview(
        request.model_copy(update={"page": 2}),
        blocks,
        {"max_input_characters": 200},
        raw,
        "text/plain",
    )
    assert second.chunks[0].sequence == 51
    empty = build_preview(
        request.model_copy(update={"query": "不存在"}),
        blocks,
        {"max_input_characters": 200},
        raw,
        "text/plain",
    )
    assert empty.chunks == [] and empty.filtered_total == 0
    assert empty.total_chunks == result.total_chunks
