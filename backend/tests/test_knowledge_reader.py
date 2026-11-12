"""Original-byte anchors and revocable, narrowly scoped embedding grants."""

from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from test_desktop import native_client
from test_identity_access import env as identity_env

from app.modules.access_keys.models import AccessKey
from app.modules.auth.models import WebSession
from app.modules.auth.service import now
from app.modules.desktop.oidc import NativeIdentity
from app.modules.knowledge.reader import normalize_parent
from app.modules.knowledge.worker import tick

env = identity_env


async def document(
    env, actor, filename="原件.md", text="# 标题\n\n  文档😀保留原貌。\n\n另一个原文段落。"
):
    response = await actor.api.post(
        "/api/v1/knowledge", json={"name": "原文测试", "audience": "organization"}
    )
    assert response.status_code == 201, response.text
    base = response.json()
    path = f"/api/v1/knowledge/{base['id']}"
    response = await actor.api.post(
        path + f"/documents?filename={filename}&upload_id={uuid4()}", content=text.encode()
    )
    assert response.status_code == 201, response.text
    doc = response.json()
    for _ in range(5):
        await tick(env.app)
    detail = (await actor.api.get(path + f"/documents/{doc['id']}")).json()
    return base, detail, path


@pytest.mark.asyncio
async def test_original_preview_anchors_unicode_and_cannot_cross_documents(env):
    admin = await env.client()
    content = "# 标题\r\n\r\n  文档😀保留原貌。\r\n\r\n另一个原文段落。"
    _, doc, path = await document(env, admin, text=content)
    chunk = doc["chunks"][0]
    url = path + f"/documents/{doc['id']}/preview"
    params = {"generation_id": doc["generation_id"], "chunk_id": chunk["id"]}
    response = await admin.api.get(url, params=params)
    assert response.status_code == 200, response.text
    manifest = response.json()
    assert "blocks" not in manifest and "text" not in manifest
    parts = [content[r["start"] : r["end"]] for r in manifest["text_ranges"]]
    assert any("😀" in part for part in parts)
    assert "\n\n".join(parts) == chunk["content"]
    original = await admin.api.get(manifest["source_url"])
    assert original.content == content.encode()
    assert original.headers["content-security-policy"] == "sandbox; default-src 'none'"
    _, other, _ = await document(env, admin)
    assert (
        await admin.api.get(url, params={**params, "chunk_id": other["chunks"][0]["id"]})
    ).status_code == 404
    assert (
        await admin.api.get(url, params={"generation_id": other["generation_id"]})
    ).status_code == 404
    filtered = await admin.api.get(path + f"/documents/{doc['id']}", params={"q": "不存在的词"})
    assert filtered.json()["chunks"] == [] and filtered.json()["total_chunks"] == 0


@pytest.mark.asyncio
async def test_csv_preview_marks_multiline_original_records(env):
    admin = await env.client()
    content = '名称,备注\r\n测试,"第一行\n第二行"\r\n结束,正常\r\n'
    _, doc, path = await document(env, admin, filename="示例.csv", text=content)
    response = await admin.api.get(
        path + f"/documents/{doc['id']}/preview", params={"chunk_id": doc["chunks"][0]["id"]}
    )
    assert response.status_code == 200, response.text
    ranges = response.json()["text_ranges"]
    assert any('"第一行\n第二行"' in content[r["start"] : r["end"]] for r in ranges)


@pytest.mark.asyncio
async def test_reader_native_scope_parent_expiry_and_parent_key_revocation(env, monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    base, doc, _ = await document(env, admin)
    endpoint = f"/api/knowledge/v1/bases/{base['id']}"
    chunk_id = doc["chunks"][0]["id"]

    async def key(grants=None):
        body = {"name": "Reader integration", "creation_id": str(uuid4())}
        if grants is not None:
            body["grants"] = grants
        response = await member.api.post("/api/v1/account/access-keys", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    broad = await key()
    limited = await key([{"kind": "knowledge", "resource_id": base["id"], "actions": ["read"]}])
    async with native_client(env) as client:
        headers = {"Authorization": "Bearer " + limited["secret"]}
        assert (
            await client.get(
                "/api/knowledge/v1/bases", headers={"Authorization": "Bearer " + broad["secret"]}
            )
        ).status_code == 403
        assert (await client.get("/api/knowledge/v1/bases", headers=headers)).json()["total"] == 1
        assert (
            await client.post(endpoint + "/search", headers=headers, json={"query": "原文"})
        ).status_code == 403
        assert (
            await client.get(endpoint + "/citations/" + chunk_id, headers=headers)
        ).status_code == 200
        issued = await client.post(
            endpoint + f"/citations/{chunk_id}/reader-session",
            headers=headers,
            json={"parent_origin": "https://host.example"},
        )
        assert issued.status_code == 200, issued.text
        grant = issued.json()
        assert grant["token"] not in grant["viewer_url"]
        reader_headers = {
            "Authorization": "Bearer " + grant["token"],
            "X-Knowledge-Parent": "https://host.example",
        }
        manifest = await client.get("/api/v1/knowledge-reader/manifest", headers=reader_headers)
        assert manifest.status_code == 200, manifest.text
        assert manifest.json()["citation_id"] == chunk_id
        assert (
            await client.get("/api/v1/knowledge-reader/source", headers=reader_headers)
        ).status_code == 200
        assert (
            await client.get(
                "/api/v1/knowledge-reader/manifest",
                headers={**reader_headers, "X-Knowledge-Parent": "https://other.example"},
            )
        ).status_code == 401
        claims = env.provider.unseal(grant["token"][4:])
        claims["exp"] = (now() - timedelta(seconds=1)).timestamp()
        expired = {**reader_headers, "Authorization": "Bearer avr_" + env.provider.seal(claims)}
        assert (
            await client.get("/api/v1/knowledge-reader/source", headers=expired)
        ).status_code == 401
        async with env.sessions() as db:
            row = await db.get(AccessKey, UUID(limited["key"]["id"]))
            row.revoked_at = now()
            await db.commit()
        assert (
            await client.get("/api/v1/knowledge-reader/source", headers=reader_headers)
        ).status_code == 401


@pytest.mark.asyncio
async def test_reader_rechecks_web_session_membership_and_framing(env, monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    admin = await env.client()
    member = await env.client("member", tenant=admin.tenant)
    base, doc, path = await document(env, admin)
    endpoint = path + f"/citations/{doc['chunks'][0]['id']}/reader-session"
    grant = (await member.api.post(endpoint, json={"parent_origin": "https://host.example"})).json()
    headers = {
        "Authorization": "Bearer " + grant["token"],
        "X-Knowledge-Parent": "https://host.example",
    }
    async with native_client(env) as client:
        assert (
            await client.get("/api/v1/knowledge-reader/manifest", headers=headers)
        ).status_code == 200
        update = {
            k: base[k]
            for k in [
                "name",
                "description",
                "member_ids",
                "department_grants",
                "chunking",
                "version",
            ]
        }
        await admin.api.put(path, json={**update, "audience": "administrators"})
        assert (
            await client.get("/api/v1/knowledge-reader/source", headers=headers)
        ).status_code == 404
        admin_grant = (
            await admin.api.post(endpoint, json={"parent_origin": "https://host.example"})
        ).json()
        async with env.sessions() as db:
            session = await db.get(WebSession, admin.session.id)
            session.requires_reauth = True
            await db.commit()
        assert (
            await client.get(
                "/api/v1/knowledge-reader/source",
                headers={**headers, "Authorization": "Bearer " + admin_grant["token"]},
            )
        ).status_code == 401
        embedded = await client.get("/embed/knowledge?parent_origin=https%3A%2F%2Fhost.example")
        assert "X-Frame-Options" not in embedded.headers
        assert (
            "frame-ancestors https://host.example;" in embedded.headers["content-security-policy"]
        )
        for url in ["/knowledge", "/embed/knowledge?parent_origin=https://host.example;evil"]:
            response = await client.get(url)
            assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize(
    "origin",
    [
        "https://app.example/path",
        "https://user:pass@host.example",
        "http://external.example",
        "https://host.example;evil",
        "null",
        "https://host.example\n",
    ],
)
def test_parent_origin_validation(origin):
    with pytest.raises(HTTPException):
        normalize_parent(origin)
