import base64
import io
import json
from datetime import timedelta
from itertools import pairwise
from uuid import uuid4
from zipfile import ZipFile

import pytest
from test_identity_access import env as identity_env

from app.modules.auth.service import now
from app.modules.knowledge.models import KnowledgeGeneration, ParserCredential
from app.modules.knowledge.parsing import local_parse, mineru_parse, split_blocks
from app.modules.knowledge.schemas import Chunking
from app.modules.knowledge.worker import tick

env = identity_env


@pytest.mark.asyncio
async def test_batch_credentials_are_atomic_deduplicated_and_private(env):
    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    payload = base64.urlsafe_b64encode(b'{"sub":"synthetic-account"}').decode().rstrip("=")
    first, second = f"header.{payload}.first", f"header.{payload}.second"
    endpoint = "/api/v1/knowledge/credentials/batch"
    body = {"keys": [first, second, first]}
    assert (await member.api.post(endpoint, json=body)).status_code == 403
    response = await admin.api.post(endpoint, json=body)
    assert response.status_code == 201, response.text
    rows = response.json()
    assert len(rows) == 2 and rows[0]["account"] == rows[1]["account"]
    assert first not in response.text and second not in response.text
    assert (await admin.api.post(endpoint, json=body)).json() == rows
    invalid = await admin.api.post(endpoint, json={"keys": ["short", "synthetic-valid-key"]})
    assert invalid.status_code == 422 and "synthetic-valid-key" not in invalid.text
    too_many = await admin.api.post(
        endpoint, json={"keys": ["synthetic-key-" + str(i) for i in range(19)]}
    )
    assert too_many.status_code == 422
    saved = (await admin.api.get("/api/v1/knowledge/defaults")).json()["credentials"]
    assert len(saved) == 2
    async with env.sessions() as db:
        for row, key in zip(rows, [first, second], strict=True):
            stored = await db.get(ParserCredential, row["id"])
            assert stored.secret != key and env.provider.unseal(stored.secret)["key"] == key


def test_positions_and_structural_chunks():
    blocks = local_parse("sample.md", ("# 项目手册\n\n" + "知识库保留原文位置。" * 100).encode())
    chunks = split_blocks(
        blocks, Chunking(target_chars=100, max_chars=200, overlap_chars=10), hard_limit=200
    )
    assert len(chunks) > 1
    for content, sources in chunks:
        assert len(content) <= 200
        assert content == "\n\n".join(
            blocks[int(s["block_id"])]["text"][s["start"] : s["end"]] for s in sources
        )
    assert blocks[0]["heading"] == "项目手册"


def test_smart_chunks_follow_sections_and_keep_title_body_and_table_together():
    values = [
        ("title", "采购说明"),
        ("text", "甲" * 300),
        ("text", "乙" * 300),
        ("title", "费用说明"),
        ("text", "丙" * 400),
        ("table", "丁" * 80),
    ]
    blocks = [
        {"block_id": str(i), "text": text, "type": kind, "page": 1 if i < 3 else 2}
        for i, (kind, text) in enumerate(values)
    ]
    chunks = split_blocks(blocks, Chunking(target_chars=400, max_chars=800))
    assert len(chunks) == 2
    assert [[s["block_id"] for s in sources] for _, sources in chunks] == [
        ["0", "1", "2"],
        ["3", "4", "5"],
    ]
    assert all(s["start"] == 0 for _, sources in chunks for s in sources)
    assert [s["page"] for s in chunks[1][1]] == [2, 2, 2]


def test_smart_chunk_preserves_oversized_block_until_model_hard_limit():
    text = "原文资料。" * 240
    blocks = [{"block_id": "0", "type": "text", "text": text, "page": 3}]
    config = Chunking(target_chars=100, max_chars=200)
    assert split_blocks(blocks, config)[0][0] == text
    chunks = split_blocks(blocks, config, hard_limit=160)
    assert len(chunks) > 1 and all(len(value) <= 160 for value, _ in chunks)
    assert "".join(value for value, _ in chunks) == text
    assert chunks[0][1][0]["start"] == 0
    assert chunks[-1][1][-1]["end"] == len(text)
    for (value, sources), (_, following) in pairwise(chunks):
        assert len(sources) == 1
        assert sources[0]["end"] == following[0]["start"]
        assert value == text[sources[0]["start"] : sources[0]["end"]]


def test_length_chunks_overlap_across_original_paragraphs_with_exact_positions():
    blocks = [
        {"block_id": str(i), "type": "text", "text": str(i) * 70, "page": i + 1} for i in range(4)
    ]
    config = Chunking(mode="normal", max_chars=100, overlap_chars=30)
    chunks = split_blocks(blocks, config)
    document = "\n\n".join(b["text"] for b in blocks)
    assert [text for text, _ in chunks] == [document[i : i + 100] for i in range(0, 280, 70)]
    assert chunks[0][1][1] == {"block_id": "1", "page": 2, "start": 0, "end": 28}
    for previous, following in pairwise(chunks):
        assert previous[0][-30:] == following[0][:30]
    # Hidden smart-mode options do not alter length-mode output.
    assert chunks == split_blocks(blocks, config.model_copy(update={"target_chars": 5000}))


def test_chunking_constraints_are_specific_to_the_selected_mode():
    Chunking(mode="smart", target_chars=100, max_chars=200, overlap_chars=900)
    Chunking(mode="normal", target_chars=100, max_chars=200, overlap_chars=150)
    with pytest.raises(ValueError, match="合并上限"):
        Chunking(mode="smart", target_chars=200, max_chars=100)
    with pytest.raises(ValueError, match="重叠长度"):
        Chunking(mode="normal", max_chars=100, overlap_chars=100)


def test_mineru_multiple_pages_and_source_boxes():
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "doc_content_list.json",
            json.dumps(
                [
                    {
                        "type": "text",
                        "text": "第一段资料",
                        "page_idx": 0,
                        "bbox": [10, 20, 500, 100],
                    },
                    {
                        "type": "text",
                        "text": "第二页资料",
                        "page_idx": 1,
                        "bbox": [20, 30, 600, 150],
                    },
                ]
            ),
        )
    _, blocks = mineru_parse(output.getvalue())
    chunks = split_blocks(blocks, Chunking())
    assert [s["page"] for s in chunks[0][1]] == [1, 2]
    assert chunks[0][1][0]["bbox"] == [0.01, 0.02, 0.5, 0.1]


def test_office_xml_does_not_resolve_entities():
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml", '<!DOCTYPE x [<!ENTITY y SYSTEM "file:///etc/passwd">]><x>&y;</x>'
        )
    with pytest.raises(ValueError):
        local_parse("sample.docx", output.getvalue())


@pytest.mark.asyncio
async def test_document_lifecycle_and_citation_permissions(env):
    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    base = (
        await admin.api.post(
            "/api/v1/knowledge", json={"name": "产品资料", "audience": "organization"}
        )
    ).json()
    assert "id" in base, base
    path = f"/api/v1/knowledge/{base['id']}"
    upload = path + f"/documents?filename=handbook.md&upload_id={uuid4()}"
    content = "# 产品手册\n\n知识库文档可以跳转到原文。".encode()
    response = await admin.api.post(
        upload, content=content, headers={"content-type": "application/octet-stream"}
    )
    assert response.status_code == 201, response.text
    doc = response.json()
    assert (await admin.api.post(upload, content=content)).json()["id"] == doc["id"]
    for _ in range(5):
        await tick(env.app)
    detail = (await admin.api.get(path + f"/documents/{doc['id']}")).json()
    assert detail["status"] == "unconfigured", detail
    assert detail["indexed_count"] == 0
    chunk = detail["chunks"][0]
    ref = path + "/citations/" + chunk["id"]
    assert (await member.api.get(ref)).status_code == 200
    result = await member.api.post(path + "/search", json={"query": "原文"})
    assert result.status_code == 200, result.text
    assert result.json()["mode"] == "keyword"
    assert result.json()["items"][0]["id"] == chunk["id"]
    source = await member.api.get(detail["source_url"])
    assert source.status_code == 200 and "no-store" in source.headers["cache-control"]
    rebuild = await admin.api.post(
        path + f"/documents/{doc['id']}/rebuild", json={"generation_id": doc["generation_id"]}
    )
    assert rebuild.status_code == 200, rebuild.text
    for _ in range(5):
        await tick(env.app)
    assert (await admin.api.get(ref)).status_code == 200
    scope = {
        k: base[k]
        for k in [
            "name",
            "description",
            "audience",
            "member_ids",
            "department_grants",
            "chunking",
            "version",
        ]
    }
    scope["audience"] = "administrators"
    updated = await admin.api.put(path, json=scope)
    assert updated.status_code == 200, updated.text
    assert (await member.api.get(ref)).status_code == 404
    assert (await member.api.get(detail["source_url"])).status_code == 404
    assert (await member.api.post(path + "/search", json={"query": "原文"})).status_code == 404
    assert (await admin.api.delete(path + f"/documents/{doc['id']}")).status_code == 204
    assert (await admin.api.get(ref)).status_code == 404


@pytest.mark.asyncio
async def test_secrets_scope_and_optimistic_defaults(env):
    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    secret = "synthetic-mineru-" + uuid4().hex
    response = await admin.api.post(
        "/api/v1/knowledge/credentials",
        json={"name": "解析账号", "account": "test-account", "key": secret},
    )
    assert response.status_code == 201, response.text
    assert secret not in response.text
    assert secret not in (await admin.api.get("/api/v1/knowledge/defaults")).text
    assert (await member.api.get("/api/v1/knowledge/defaults")).status_code == 403
    assert (
        await member.api.post("/api/v1/knowledge", json={"name": "越权创建"})
    ).status_code == 403
    async with env.sessions() as db:
        credential = await db.get(ParserCredential, response.json()["id"])
        assert credential.secret != secret
        assert env.provider.unseal(credential.secret)["key"] == secret
    saved = await admin.api.put("/api/v1/knowledge/defaults", json={"version": 0})
    assert saved.status_code == 200, saved.text
    assert (
        await admin.api.put("/api/v1/knowledge/defaults", json={"version": 0})
    ).status_code == 409


@pytest.mark.asyncio
async def test_crashed_external_submission_not_replayed(env):
    admin = await env.client()
    base = (await admin.api.post("/api/v1/knowledge", json={"name": "任务恢复"})).json()
    path = f"/api/v1/knowledge/{base['id']}"
    doc = (
        await admin.api.post(
            path + f"/documents?filename=test.pdf&upload_id={uuid4()}", content=b"%PDF-1.7\n"
        )
    ).json()
    async with env.sessions() as db:
        job = await db.get(KnowledgeGeneration, doc["generation_id"])
        job.submission_pending = True
        job.lease_until = now() - timedelta(seconds=1)
        await db.commit()
    await tick(env.app)
    async with env.sessions() as db:
        job = await db.get(KnowledgeGeneration, doc["generation_id"])
        assert job.status == "uncertain"
    assert not await tick(env.app)


@pytest.mark.asyncio
async def test_real_embedding_pipeline_billing_and_revocation(env):
    from llm_billing_helpers import billing
    from sqlalchemy import select
    from test_llm_retrieval import configured, upstream
    from test_mcp import listening

    from app.modules.llm.models import ModelCall
    from app.modules.members.models import Membership

    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    await billing(admin)
    upstream_app, requests = upstream()
    async with listening(upstream_app) as url:
        model, _ = await configured(env, admin, url, enabled=True)
        response = await admin.api.put(
            "/api/v1/knowledge/defaults", json={"version": 0, "embedding_model_id": model["id"]}
        )
        assert response.status_code == 200, response.text
        base = (
            await admin.api.post(
                "/api/v1/knowledge", json={"name": "向量知识库", "audience": "organization"}
            )
        ).json()
        path = "/api/v1/knowledge/" + base["id"]
        doc = (
            await admin.api.post(
                path + f"/documents?filename=manual.txt&upload_id={uuid4()}",
                content="组织知识库检索说明".encode(),
            )
        ).json()
        for _ in range(8):
            await tick(env.app)
        result = (await admin.api.get(path + "/documents/" + doc["id"])).json()
        assert result["status"] == "ready", result
        assert result["indexed_count"] == 1
        query = await member.api.post(path + "/search", json={"query": "知识库"})
        assert query.status_code == 200, query.text
        assert query.json()["mode"] == "hybrid"
        assert len(requests) == 2
        async with env.sessions() as db:
            calls = list(await db.scalars(select(ModelCall).order_by(ModelCall.created_at)))
            assert {c.source for c in calls} == {"knowledge_index", "knowledge_search"}
            assert all(c.actor_id == admin.user.id for c in calls)
            executor = await db.get(Membership, admin.member.id)
            executor.status = "paused"
            await db.commit()
        blocked = await member.api.post(path + "/search", json={"query": "知识库"})
        assert blocked.status_code == 403, blocked.text
        assert len(requests) == 2


@pytest.mark.asyncio
async def test_mineru_account_cooldown_selects_other_account(env):
    from unittest.mock import patch

    import httpx2
    from fastapi import Request

    from app.modules.knowledge import mineru
    from app.modules.knowledge.models import ParserCredential

    admin = await env.client()
    for name, account in [("one", "a"), ("two", "a"), ("three", "b")]:
        await admin.api.post(
            "/api/v1/knowledge/credentials",
            json={"name": name, "account": account, "key": "synthetic-key-" + name},
        )
    request = Request({"type": "http", "app": env.app, "headers": []})
    original = httpx2.AsyncClient
    async with env.sessions() as db:
        key = await mineru.credential(db, admin.tenant.id)
        transport = httpx2.MockTransport(
            lambda r: httpx2.Response(429, headers={"retry-after": "120"})
        )
        with patch.object(
            mineru.httpx2, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
        ):
            with pytest.raises(mineru.ParserWait):
                await mineru.api(request, db, key, "/api/v4/file-urls/batch", {"files": []})
        next_key = await mineru.credential(db, admin.tenant.id)
        assert next_key.account != key.account
        from sqlalchemy import select

        same = list(
            await db.scalars(
                select(ParserCredential).where(ParserCredential.account == key.account)
            )
        )
        assert all(c.cooldown_until > now() + timedelta(seconds=60) for c in same)


@pytest.mark.asyncio
async def test_knowledge_migration_chain_preserves_existing_records(monkeypatch):
    import os

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    url = os.getenv("ACTVERO_TEST_DATABASE_URL")
    if not url:
        pytest.skip("ACTVERO_TEST_DATABASE_URL required")
    monkeypatch.setenv("ACTVERO_DATABASE_URL", url)
    schema = "test_knowledge_migration_" + uuid4().hex
    owner = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    cfg = Config("alembic.ini")
    async with owner.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        async with engine.begin() as conn:

            def migrate(sync, revision, downgrade=False):
                cfg.attributes["connection"] = sync
                (command.downgrade if downgrade else command.upgrade)(cfg, revision)

            await conn.run_sync(migrate, "127s_departments")
            before = (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one()
            await conn.run_sync(migrate, "128t_knowledge_base")
            after = (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one()
            assert before == after
            assert (
                await conn.execute(text("SELECT count(*) FROM knowledge_bases"))
            ).scalar_one() == 0
            await conn.run_sync(migrate, "127s_departments", True)
            assert (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one() == before
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
