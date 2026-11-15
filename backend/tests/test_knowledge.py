import base64
import io
import json
from datetime import timedelta
from itertools import pairwise
from uuid import uuid4
from zipfile import ZipFile

import pytest
from PIL import Image
from test_identity_access import env as identity_env

from app.modules.auth.service import now
from app.modules.knowledge.models import KnowledgeGeneration, ParserCredential
from app.modules.knowledge.parsing import (
    local_parse,
    mineru_parse,
    split_blocks,
    split_parent_child,
)
from app.modules.knowledge.schemas import Chunking
from app.modules.knowledge.worker import tick

env = identity_env


@pytest.mark.asyncio
async def test_knowledge_icon_selection_upload_and_reset(env):
    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    root = "/api/v1/knowledge"
    created = await admin.api.post(
        root,
        json={
            "name": "产品资料",
            "audience": "organization",
            "icon_selection": {"source": "library", "key": "lucide:file-text"},
        },
    )
    assert created.status_code == 201, created.text
    base = created.json()
    path = f"{root}/{base['id']}"
    endpoint = path + "/icon"
    assert base["icon"]["key"] == "lucide:file-text"
    assert base["icon"]["image"].startswith("data:image/svg+xml;base64,")
    assert (await member.api.get(path)).json()["icon"] == base["icon"]

    payload = {"version": base["version"], "icon_selection": {"source": "auto"}}
    assert (await member.api.patch(endpoint, json=payload)).status_code == 403
    invalid = {
        **payload,
        "icon_selection": {"source": "upload", "image": "https://example.invalid/icon.png"},
    }
    assert (await admin.api.patch(endpoint, json=invalid)).status_code == 422
    with io.BytesIO() as output:
        Image.new("RGB", (20, 12), "blue").save(output, format="PNG")
        data_url = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    edited = await admin.api.patch(
        endpoint,
        json={**payload, "icon_selection": {"source": "upload", "image": data_url}},
    )
    assert edited.status_code == 200, edited.text
    updated = edited.json()
    icon = updated["icon"]
    assert icon["source"] == "upload" and icon["image"].startswith("data:image/webp;base64,")
    with Image.open(io.BytesIO(base64.b64decode(icon["image"].split(",", 1)[1]))) as image:
        assert image.size == (256, 256)
    assert (await admin.api.patch(endpoint, json=payload)).status_code == 409
    assert (await member.api.get(root)).json()["items"][0]["icon"] == icon

    saved = await admin.api.put(
        path,
        json={"version": updated["version"], "name": "手册", "audience": "organization"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["icon"] == icon
    reset = await admin.api.patch(endpoint, json={**payload, "version": saved.json()["version"]})
    assert reset.status_code == 200, reset.text
    assert reset.json()["icon"] == {"source": "auto", "key": "", "image": ""}


@pytest.mark.asyncio
async def test_batch_credentials_are_atomic_deduplicated_and_private(env):
    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    payload = base64.urlsafe_b64encode(b'{"sub":"synthetic-account"}').decode().rstrip("=")
    first, second = f"header.{payload}.first", f"header.{payload}.second"
    endpoint = "/api/v1/knowledge/credentials/batch"
    body = {"keys": [first, second, first], "name": " 解析账号 "}
    assert (await member.api.post(endpoint, json=body)).status_code == 403
    response = await admin.api.post(endpoint, json=body)
    assert response.status_code == 201, response.text
    rows = response.json()
    assert len(rows) == 2 and rows[0]["account"] == rows[1]["account"]
    assert [row["name"] for row in rows] == ["解析账号 1", "解析账号 2"]
    assert first not in response.text and second not in response.text
    assert (await admin.api.post(endpoint, json=body)).json() == rows
    rename_path = f"/api/v1/knowledge/credentials/{rows[0]['id']}"
    assert (await member.api.patch(rename_path, json={"name": "新名称"})).status_code == 403
    assert (await admin.api.patch(rename_path, json={"name": "  "})).status_code == 422
    renamed = await admin.api.patch(rename_path, json={"name": " 文档解析 "})
    assert renamed.status_code == 200
    assert renamed.json() == {**rows[0], "name": "文档解析"}
    assert first not in renamed.text
    invalid = await admin.api.post(endpoint, json={"keys": ["short", "synthetic-valid-key"]})
    assert invalid.status_code == 422 and "synthetic-valid-key" not in invalid.text
    too_many = await admin.api.post(
        endpoint, json={"keys": ["synthetic-key-" + str(i) for i in range(19)]}
    )
    assert too_many.status_code == 422
    saved = (await admin.api.get("/api/v1/knowledge/defaults")).json()["credentials"]
    assert len(saved) == 2
    assert "文档解析" in [row["name"] for row in saved]
    async with env.sessions() as db:
        for row, key in zip(rows, [first, second], strict=True):
            stored = await db.get(ParserCredential, row["id"])
            assert stored.secret != key and env.provider.unseal(stored.secret)["key"] == key


@pytest.mark.asyncio
async def test_mineru_key_deletion_waits_for_pending_parse_and_preserves_document(env):
    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    credentials = "/api/v1/knowledge/credentials/batch"
    keys = {"keys": ["synthetic-mineru-first", "synthetic-mineru-second"]}
    first, second = (await admin.api.post(credentials, json=keys)).json()
    path = f"/api/v1/knowledge/credentials/{first['id']}"
    base = (await admin.api.post("/api/v1/knowledge", json={"name": "解析任务"})).json()
    documents = f"/api/v1/knowledge/{base['id']}/documents"
    doc = (
        await admin.api.post(
            documents + f"?filename=sample.pdf&upload_id={uuid4()}",
            content=b"%PDF-1.7\n",
            headers={"content-type": "application/octet-stream"},
        )
    ).json()
    generation_id = doc["generation_id"]
    async with env.sessions() as db:
        job = await db.get(KnowledgeGeneration, generation_id)
        job.credential_id = first["id"]
        job.batch_id = "synthetic-batch"
        job.status = "waiting"
        await db.commit()
    assert (await member.api.delete(path)).status_code == 403
    assert (await admin.api.delete(path)).status_code == 409
    async with env.sessions() as db:
        job = await db.get(KnowledgeGeneration, generation_id)
        job.status = "ready"
        await db.commit()
    assert (await admin.api.delete(path)).status_code == 204
    assert (await admin.api.delete(path)).status_code == 404
    assert (await admin.api.get(documents + f"/{doc['id']}")).json()["status"] == "ready"
    async with env.sessions() as db:
        assert await db.get(ParserCredential, first["id"]) is None
    added = (await admin.api.post(credentials, json=keys)).json()
    assert added[0]["id"] != first["id"] and added[0]["name"] == "Key 1"
    assert added[1] == second


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


def test_smart_chunk_splits_long_paragraphs_at_sentences():
    text = "原文资料。" * 240
    blocks = [{"block_id": "0", "type": "text", "text": text, "page": 3}]
    config = Chunking(target_chars=100, max_chars=200)
    regular = split_blocks(blocks, config)
    assert len(regular) > 1 and all(len(value) <= 200 for value, _ in regular)
    assert "".join(value for value, _ in regular) == text
    assert all(value.endswith("。") for value, _ in regular)
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


def test_parent_child_keeps_positions_when_splitting_a_long_block():
    text = "原文🙂片段。" * 100
    blocks = local_parse("sample.txt", text.encode())
    groups = split_parent_child(
        blocks,
        Chunking(structure="parent_child", target_chars=120, max_chars=180, child_chars=70),
        hard_limit=60,
    )
    assert len(groups) > 1
    assert "".join(parent for parent, _ in groups) == text
    for parent, children in groups:
        assert len(parent) <= 180
        assert "".join(child for child, _ in children) == parent
        for child, refs in children:
            assert len(child) <= 60
            assert child == text[refs[0]["start"] : refs[0]["end"]]


@pytest.mark.asyncio
async def test_parent_child_retrieves_one_context_and_keeps_historical_child_citation(env):
    admin = await env.client()
    response = await admin.api.post(
        "/api/v1/knowledge",
        json={
            "name": "父子切片",
            "retrieval": {"mode": "keyword"},
            "chunking": {
                "structure": "parent_child",
                "mode": "normal",
                "max_chars": 240,
                "child_chars": 60,
                "overlap_chars": 0,
            },
        },
    )
    assert response.status_code == 201, response.text
    base = response.json()
    path = f"/api/v1/knowledge/{base['id']}"
    parent = "上下文" * 20 + "命中词" * 40 + "上下文" * 20
    text = parent + "其他内容" * 60
    upload = await admin.api.post(
        path + f"/documents?filename=handbook.txt&upload_id={uuid4()}",
        content=text.encode(),
    )
    assert upload.status_code == 201, upload.text
    doc = upload.json()
    doc_path = path + f"/documents/{doc['id']}"
    for _ in range(5):
        await tick(env.app)
    detail = (await admin.api.get(doc_path)).json()
    assert detail["status"] == "ready", detail
    assert detail["chunk_count"] == 8 and detail["character_count"] == len(text)
    assert detail["chunk_structure"] == "parent_child"
    assert detail["chunks"][0]["parent_id"] == detail["chunks"][2]["parent_id"]
    assert detail["chunks"][2]["parent_id"] != detail["chunks"][4]["parent_id"]
    search = await admin.api.post(path + "/search", json={"query": "命中词"})
    assert search.status_code == 200, search.text
    (hit,) = search.json()["items"]
    assert hit["parent_context"]["content"] == parent
    assert hit["content"] == "命中词" * 20
    assert hit["sources"][0]["start"] in {60, 120}
    preview = await admin.api.get(
        doc_path + f"/preview?generation_id={doc['generation_id']}&chunk_id={hit['id']}"
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["text_ranges"][0]["start"] == hit["sources"][0]["start"]
    rebuilt = await admin.api.post(
        doc_path + "/rebuild",
        json={"generation_id": doc["generation_id"], "chunking": {"structure": "general"}},
    )
    assert rebuilt.status_code == 200, rebuilt.text
    for _ in range(5):
        await tick(env.app)
    current = (await admin.api.get(doc_path)).json()
    assert current["chunk_structure"] == "general"
    assert current["chunks"][0]["parent_id"] is None
    assert (await admin.api.get(path + f"/citations/{hit['id']}")).status_code == 200
    old = (await admin.api.get(doc_path + f"?generation_id={doc['generation_id']}")).json()
    assert old["chunk_structure"] == "parent_child"


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
    from test_llm_catalog import create as create_model
    from test_llm_retrieval import PRICE, configured

    from app.modules.llm.models import CatalogModel

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
    model, channel = await configured(env, admin, "http://127.0.0.1:18080", enabled=True)
    endpoint = "/api/v1/knowledge/defaults"
    saved = await admin.api.put(endpoint, json={"version": 0, "embedding_model_id": model["id"]})
    assert saved.status_code == 200, saved.text
    assert (await admin.api.put(endpoint, json={"version": 0})).status_code == 409
    async with env.sessions() as db:
        stored_model = await db.get(CatalogModel, model["id"])
        stored_model.archived = True
        await db.commit()
    rerank = await create_model(
        admin,
        slug="team-rerank",
        kind="rerank",
        bindings=[{"channel_id": channel["id"], "upstream_id": "upstream", "enabled": True}],
        access={"enabled": True, "channel_id": channel["id"], "upstream_id": "upstream"},
        budget_price=PRICE,
    )
    saved = await admin.api.put(
        endpoint,
        json={
            "version": saved.json()["version"],
            "embedding_model_id": model["id"],
            "rerank_model_id": rerank["id"],
            "rerank_enabled": True,
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["rerank_model_id"] == rerank["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", ["submission_pending", "inference_pending"])
async def test_crashed_external_submission_not_replayed(env, pending):
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
        setattr(job, pending, True)
        job.lease_until = now() - timedelta(seconds=1)
        await db.commit()
    await tick(env.app)
    async with env.sessions() as db:
        job = await db.get(KnowledgeGeneration, doc["generation_id"])
        assert job.status == "failed"
        assert getattr(job, pending) is True
    assert not await tick(env.app)
    detail = (await admin.api.get(path + f"/documents/{doc['id']}")).json()
    assert detail["status"] == "failed"
    assert "核对" not in detail["error"]


@pytest.mark.asyncio
async def test_legacy_stopped_job_exposes_failure_without_replaying(env):
    admin = await env.client()
    base = (await admin.api.post("/api/v1/knowledge", json={"name": "旧任务"})).json()
    path = f"/api/v1/knowledge/{base['id']}"
    doc = (
        await admin.api.post(
            path + f"/documents?filename=test.md&upload_id={uuid4()}", content=b"old document"
        )
    ).json()
    async with env.sessions() as db:
        job = await db.get(KnowledgeGeneration, doc["generation_id"])
        job.status = "uncertain"
        job.error = "请核对服务任务或模型调用记录后重新处理"
        job.inference_pending = True
        await db.commit()
    assert not await tick(env.app)
    listed = (await admin.api.get(path + "/documents")).json()[0]
    assert listed["status"] == "failed" and "核对" not in listed["error"]
    detail = (await admin.api.get(path + f"/documents/{doc['id']}")).json()
    assert detail["status"] == "failed" and detail["error"] == listed["error"]
    assert (await admin.api.get(path)).json()["status"] == "attention"
    retried = await admin.api.post(
        path + f"/documents/{doc['id']}/rebuild",
        json={
            "generation_id": doc["generation_id"],
        },
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "queued"
    assert retried.json()["generation_id"] != doc["generation_id"]
    async with env.sessions() as db:
        old = await db.get(KnowledgeGeneration, doc["generation_id"])
        assert old.inference_pending is True


@pytest.mark.asyncio
async def test_organization_knowledge_usage_is_independent_of_the_saving_admin(env):
    from decimal import Decimal

    from sqlalchemy import select
    from test_llm_retrieval import configured, upstream
    from test_mcp import listening

    from app.modules.llm.models import ModelCall, UsageSettlement
    from app.modules.members.models import Membership

    admin = await env.client()
    editor = await env.client(tenant=admin.tenant)
    member = await env.client("member", tenant=admin.tenant)
    upstream_app, requests = upstream()
    async with listening(upstream_app) as url:
        model, _ = await configured(env, admin, url, enabled=True)
        response = await admin.api.put(
            "/api/v1/knowledge/defaults", json={"version": 0, "embedding_model_id": model["id"]}
        )
        assert response.status_code == 200, response.text
        async with env.sessions() as db:
            saved_by = await db.get(Membership, admin.member.id)
            saved_by.status = "paused"
            await db.commit()
        base = (
            await editor.api.post(
                "/api/v1/knowledge", json={"name": "向量知识库", "audience": "organization"}
            )
        ).json()
        path = "/api/v1/knowledge/" + base["id"]
        doc = (
            await editor.api.post(
                path + f"/documents?filename=manual.txt&upload_id={uuid4()}",
                content="组织知识库检索说明".encode(),
            )
        ).json()
        for _ in range(8):
            await tick(env.app)
        result = (await editor.api.get(path + "/documents/" + doc["id"])).json()
        assert result["status"] == "ready", result
        assert result["indexed_count"] == 1
        query = await member.api.post(path + "/search", json={"query": "知识库"})
        assert query.status_code == 200, query.text
        assert query.json()["mode"] == "hybrid"
        assert len(requests) == 2
        async with env.sessions() as db:
            calls = list(await db.scalars(select(ModelCall).order_by(ModelCall.created_at)))
            assert [(c.source, c.actor_id) for c in calls] == [
                ("knowledge_index", editor.user.id),
                ("knowledge_search", member.user.id),
            ]
            for call in calls:
                charge = await db.get(UsageSettlement, call.id)
                assert charge.status == "settled" and charge.amount == Decimal("0.000002")
                assert charge.member_id is charge.conversion_id is charge.ratio is None
            caller = await db.get(Membership, member.member.id)
            caller.status = "paused"
            await db.commit()
        detail = await editor.api.get(f"/api/v1/llm/calls/{calls[-1].id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["call"]["member_name"] == "组织知识库"
        assert detail.json()["settlement"]["currency"] == "USD"
        assert detail.json()["settlement"]["points"] is None
        personal = (await editor.api.get("/api/v1/account/llm/usage")).json()
        assert personal == {"items": [], "total": 0}
        overview = (await editor.api.get("/api/v1/account/overview")).json()
        assert overview["calls"] == 0
        blocked = await member.api.post(path + "/search", json={"query": "知识库"})
        assert blocked.status_code == 403, blocked.text
        assert len(requests) == 2


@pytest.mark.asyncio
async def test_library_retrieval_is_saved_and_controls_gateway_calls(env):
    from test_llm_catalog import create as create_model
    from test_llm_retrieval import PRICE, configured, upstream
    from test_mcp import listening

    admin = await env.client()
    root = "/api/v1/knowledge"
    app, requests = upstream()
    async with listening(app) as url:
        embedding, channel = await configured(env, admin, url, enabled=True)
        reranker = await create_model(
            admin,
            slug="team-rerank",
            kind="rerank",
            bindings=[{"channel_id": channel["id"], "upstream_id": "upstream", "enabled": True}],
            budget_price=PRICE,
            access={
                "enabled": True,
                "audience": "organization",
                "channel_id": channel["id"],
                "upstream_id": "upstream",
            },
        )
        saved = await admin.api.put(
            root + "/defaults",
            json={"version": 0, "embedding_model_id": embedding["id"]},
        )
        assert saved.status_code == 200, saved.text
        stale = await admin.api.post(root, json={"name": "旧版本", "defaults_version": 0})
        assert stale.status_code == 409
        inherited = await admin.api.post(root, json={"name": "使用组织默认", "defaults_version": 1})
        assert inherited.status_code == 201, inherited.text
        assert inherited.json()["retrieval"]["mode"] == "hybrid"
        saved = await admin.api.put(root + "/defaults", json={"version": 1})
        assert saved.status_code == 200, saved.text
        assert (await admin.api.get(root + "/" + inherited.json()["id"])).json()[
            "retrieval"
        ] == inherited.json()["retrieval"]

        base = await admin.api.post(
            root,
            json={
                "name": "自定义检索",
                "retrieval": {"mode": "keyword", "rerank_model_id": reranker["id"]},
            },
        )
        assert base.status_code == 201, base.text
        doc_path = root + "/" + base.json()["id"]
        doc = await admin.api.post(
            doc_path + f"/documents?filename=manual.txt&upload_id={uuid4()}",
            content="组织知识库检索说明".encode(),
        )
        assert doc.status_code == 201, doc.text
        for _ in range(5):
            await tick(env.app)
        assert requests == []
        document_url = doc_path + "/documents/" + doc.json()["id"]
        result = (await admin.api.get(document_url)).json()
        assert result["status"] == "ready" and result["indexed_count"] == 0, result
        search = await admin.api.post(doc_path + "/search", json={"query": "知识库"})
        assert search.status_code == 200, search.text
        assert search.json()["reranked"] and len(requests) == 1
        assert "documents" in requests[0][1]

        updated = await admin.api.put(
            doc_path,
            json={
                "name": "自定义检索",
                "version": base.json()["version"],
                "retrieval": {
                    "mode": "vector",
                    "embedding_model_id": embedding["id"],
                    "vector_weight": 70,
                },
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["retrieval"]["vector_weight"] == 70
        search = await admin.api.post(doc_path + "/search", json={"query": "知识库"})
        assert search.json() == {"mode": "vector", "reranked": False, "items": []}
        rebuilt = await admin.api.post(
            document_url + "/rebuild", json={"generation_id": result["generation_id"]}
        )
        assert rebuilt.status_code == 200, rebuilt.text
        for _ in range(6):
            await tick(env.app)
        search = await admin.api.post(doc_path + "/search", json={"query": "没有相同词项"})
        assert search.status_code == 200, search.text
        assert search.json()["mode"] == "vector" and len(search.json()["items"]) == 1
        assert len(requests) == 3
        hybrid = await admin.api.put(
            doc_path,
            json={
                "name": "自定义检索",
                "version": updated.json()["version"],
                "retrieval": {
                    "mode": "hybrid",
                    "embedding_model_id": embedding["id"],
                    "vector_weight": 70,
                },
            },
        )
        assert hybrid.status_code == 200, hybrid.text
        search = await admin.api.post(doc_path + "/search", json={"query": "没有相同词项"})
        assert search.status_code == 200, search.text
        assert search.json()["items"][0]["score"] == pytest.approx(1.4 / 61)


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
async def test_organization_knowledge_newapi_uses_native_ledger(env, monkeypatch, confirmed):
    from decimal import Decimal

    from fastapi import Request
    from llm_billing_helpers import billing as setup_billing
    from pydantic import SecretStr
    from sqlalchemy import select
    from test_llm_retrieval import upstream
    from test_mcp import listening
    from test_model_gateway import channel

    from app.modules.llm.models import UsageSettlement
    from app.modules.model_gateway import billing, client
    from app.modules.model_gateway.config import NewApiConnection

    admin = await env.client()
    await setup_billing(admin)  # Required by the existing model publication workflow.
    upstream_app, requests = upstream()
    request_id = uuid4().hex

    @upstream_app.middleware("http")
    async def correlate(request, call_next):
        response = await call_next(request)
        response.headers["X-Oneapi-Request-Id"] = request_id
        return response

    async def native(request, tenant_id, method, path, **kwargs):
        if path == "/api/channel/":
            return {"items": [channel(models="public")], "total": 1}
        if path == "/api/option/model_pricing":
            return {"entries": [{"model_name": "public", "effective": {"ModelRatio": 1}}]}
        if path == "/api/status":
            return {"quota_per_unit": 500000}
        assert path == "/api/log/", path
        return {
            "items": [
                {
                    "id": 1,
                    "request_id": request_id,
                    "token_id": 51,
                    "model_name": "public",
                    "type": 2,
                    "quota": 100,
                    "prompt_tokens": 10,
                    "completion_tokens": 0,
                    "other": json.dumps(
                        {
                            "admin_info": {
                                "usage_billing_path": "billing-usage-openai"
                                if confirmed
                                else "estimated"
                            }
                        }
                    ),
                }
            ]
        }

    async with listening(upstream_app) as url:
        env.provider.settings.newapi_connections = [
            NewApiConnection(
                tenant_id=admin.tenant.id,
                base_url=url,
                management_token=SecretStr("management"),
                relay_key=SecretStr("relay-only"),
                relay_token_id=51,
            )
        ]
        env.provider.settings.llm_allowed_private_origins = [url]
        monkeypatch.setattr(client, "call", native)
        request = Request({"type": "http", "app": env.app})
        env.app.state.llm_outbox.reconcile = lambda record: billing.reconcile(request, record)
        published = await admin.api.put(
            "/api/v1/model-gateway/publication",
            json={
                "model_name": "public",
                "name": "向量模型",
                "enabled": True,
                "kind": "embedding",
                "retrieval": {"dimensions": 3, "embedding_space": "fixture-v1"},
            },
        )
        assert published.status_code == 200, published.text
        saved = await admin.api.put(
            "/api/v1/knowledge/defaults",
            json={"embedding_model_id": published.json()["data"]["id"]},
        )
        assert saved.status_code == 200, saved.text
        base = (await admin.api.post("/api/v1/knowledge", json={"name": "网关用量"})).json()
        documents = f"/api/v1/knowledge/{base['id']}/documents"
        uploaded = await admin.api.post(
            documents + f"?filename=manual.txt&upload_id={uuid4()}", content=b"test"
        )
        assert uploaded.status_code == 201, uploaded.text
        for _ in range(8):
            await tick(env.app)
        doc = await admin.api.get(documents + "/" + uploaded.json()["id"])
        assert doc.json()["status"] == "ready", doc.text
        assert len(requests) == 1
        assert "dimensions" not in requests[0][1]
        async with env.sessions() as db:
            charge = (await db.scalars(select(UsageSettlement))).one()
            assert charge.member_id is charge.conversion_id is charge.ratio is None
            assert charge.status == ("settled" if confirmed else "review")
            assert charge.amount == (Decimal("0.0002") if confirmed else None)


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
            await conn.run_sync(migrate, "129u_knowledge_org_usage")
            columns = await conn.execute(
                text("""
                    SELECT column_name, is_nullable FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = 'llm_settlements'
                        AND column_name IN ('member_id', 'conversion_id', 'ratio')
                    """)
            )
            assert dict(columns.all()) == dict.fromkeys(
                ("member_id", "conversion_id", "ratio"), "YES"
            )
            await conn.run_sync(migrate, "130v_knowledge_retrieval")
            await conn.execute(text("SELECT retrieval FROM knowledge_bases"))
            await conn.run_sync(migrate, "131w_knowledge_parent_chunks")
            await conn.execute(text("SELECT character_count FROM knowledge_generations"))
            await conn.execute(text("SELECT parent_id FROM knowledge_chunks"))
            await conn.execute(text("SELECT content FROM knowledge_parent_chunks"))
            await conn.run_sync(migrate, "132x_knowledge_icon")
            await conn.execute(text("SELECT icon_selection FROM knowledge_bases"))
            await conn.run_sync(migrate, "127s_departments", True)
            assert (
                await conn.execute(text("SELECT to_jsonb(i) FROM installation i"))
            ).scalar_one() == before
    finally:
        await engine.dispose()
        async with owner.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await owner.dispose()
