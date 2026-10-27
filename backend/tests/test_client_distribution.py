"""Release transactions use real PostgreSQL; object storage and transfers are controlled doubles."""

import base64
import gzip
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_identity_access import env  # noqa: F401
from test_platform_settings import operator

from app.modules.auth.service import now
from app.modules.client_distribution import worker
from app.modules.client_distribution.models import ClientArtifact, ClientJob, ClientStorage
from app.modules.client_distribution.schemas import DistributionSave
from app.modules.client_distribution.service import newer
from app.modules.client_distribution.storage import ClientError, ObjectStore
from app.modules.desktop.oidc import NativeIdentity
from app.modules.desktop.service import pkce
from app.modules.object_storage import network
from app.modules.object_storage import router as storage_router
from app.modules.tenants.models import PlatformOperator

BASE = "/api/v1/platform/client-distribution"
pytestmark = pytest.mark.asyncio


def checksum(data):
    return base64.b64encode(hashlib.sha512(data).digest()).decode()


async def release(api, version="1.0.0"):
    ident = str(uuid4())
    response = await api.put(
        BASE + "/releases/" + ident,
        json={
            "expected_revision": 0,
            "version": version,
            "channel": "latest",
            "minimum_os": {
                "win-x64": "Windows 10",
                "win-arm64": "Windows 11 ARM64",
                "mac-arm64": "macOS 13",
            },
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def add(api, row, role, data, target="win-x64", **changes):
    row = (await api.get(BASE + "/releases/" + row["id"])).json()
    filename = (
        "app.exe" if target.startswith("win-") else "app.dmg" if role == "installer" else "app.zip"
    )
    if role == "blockmap":
        filename += ".blockmap"
    response = await api.put(
        BASE + "/releases/" + row["id"] + "/artifacts/" + str(uuid4()),
        json={
            "expected_revision": row["revision"],
            "target": target,
            "role": role,
            "filename": filename,
            "url": "https://files.example.com/" + filename,
            "size_bytes": len(data),
            "sha512": checksum(data),
            **changes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def files(monkeypatch, payload=b"signed-installer-fixture", *, range_ok=True):
    blockmap = gzip.compress(
        json.dumps(
            {
                "version": "2",
                "files": [{"offset": 0, "sizes": [len(payload)], "checksums": ["fixture"]}],
            }
        ).encode()
    )

    @asynccontextmanager
    async def download(url, settings):
        content = blockmap if url.split("?", 1)[0].endswith("blockmap") else payload
        yield httpx.Response(200, content=content)

    monkeypatch.setattr(worker, "download", download)
    monkeypatch.setattr(worker, "check_range", AsyncMock(return_value=range_ok))
    return payload, blockmap


async def verified(env, monkeypatch, actor, version="1.0.0", *, target="win-x64", range_ok=True):  # noqa: F811
    row = await release(actor.api, version)
    payload, blockmap = files(monkeypatch, range_ok=range_ok)
    for role, data in [("payload", payload), ("blockmap", blockmap)]:
        await add(actor.api, row, role, data, target)
        assert await worker.run_once(env.app)
    if target.startswith("mac-"):
        await add(actor.api, row, "installer", payload, target)
        assert await worker.run_once(env.app)
    return (await actor.api.get(BASE + "/releases/" + row["id"])).json()


async def plan(api, row, targets=None):
    response = await api.post(
        BASE + "/releases/" + row["id"] + "/plan",
        json={
            "expected_revision": row["revision"],
            "targets": targets or ["win-x64"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_publish_snapshots_deltas_and_withdraw_keep_old_blockmaps(env, monkeypatch):  # noqa: F811
    env.provider.settings.app_url = "https://platform.example.com"
    actor = await operator(env)
    row = await verified(env, monkeypatch, actor)
    draft_feed = "/api/v1/client-updates/actvero/win-x64/latest.yml"
    assert (await actor.api.get(draft_feed)).status_code == 404
    prepared = await plan(actor.api, row)
    endpoint = BASE + "/releases/" + row["id"] + "/publish"
    published = await actor.api.post(endpoint, json={"plan_id": prepared["id"]})
    assert published.status_code == 200, published.text
    repeat = await actor.api.post(endpoint, json={"plan_id": prepared["id"]})
    assert repeat.json()["revision"] == published.json()["revision"]
    feed = await actor.api.get(draft_feed)
    assert feed.status_code == 200 and "actvero-1.0.0-win-x64.exe" in feed.text
    assert feed.headers["cache-control"] == "no-store"
    public = await actor.api.get("/api/v1/platform/downloads/public")
    assert public.status_code == 200 and public.json()["items"][0]["version"] == "1.0.0"
    for action in ["publish", "withdraw"]:
        response = await actor.api.post(
            "/api/v1/platform/downloads/" + row["id"] + "/" + action,
            json={"expected_revision": published.json()["revision"]},
        )
        assert response.status_code == 409
    withdrawal = await actor.api.post(
        BASE + "/releases/" + row["id"] + "/withdraw",
        json={"expected_revision": published.json()["revision"]},
    )
    assert withdrawal.status_code == 200
    assert (await actor.api.get(draft_feed)).status_code == 404
    old_map = await actor.api.get(
        "/api/v1/client-artifacts/latest/win-x64/actvero-1.0.0-win-x64.exe.blockmap"
    )
    assert old_map.status_code == 307
    assert old_map.headers["location"].endswith("app.exe.blockmap")
    assert (await actor.api.get("/api/v1/platform/downloads/public")).json()["items"] == []
    older = await verified(env, monkeypatch, actor, "0.9.0")
    rejected = await actor.api.post(
        BASE + "/releases/" + older["id"] + "/plan",
        json={"expected_revision": older["revision"], "targets": ["win-x64"]},
    )
    assert rejected.status_code == 409


async def test_publish_rechecks_plan_revision_heads_and_actor(env, monkeypatch):  # noqa: F811
    actor, other = await operator(env), await operator(env)
    row = await verified(env, monkeypatch, actor)
    first = await plan(actor.api, row)
    url = BASE + "/releases/" + row["id"] + "/publish"
    assert (await other.api.post(url, json={"plan_id": first["id"]})).status_code == 404
    async with env.sessions() as db:
        artifact = await db.get(ClientArtifact, UUID(row["artifacts"][0]["id"]))
        artifact.status = "failed"
        await db.commit()
    assert (await actor.api.post(url, json={"plan_id": first["id"]})).status_code == 422
    async with env.sessions() as db:
        (await db.get(PlatformOperator, actor.user.id)).status = "paused"
        await db.commit()
    assert (await actor.api.post(url, json={"plan_id": first["id"]})).status_code == 403


async def test_reject_missing_mac_installer_bad_hash_and_non_range_feed(env, monkeypatch):  # noqa: F811
    actor = await operator(env)
    row = await verified(env, monkeypatch, actor, range_ok=False)
    response = await actor.api.post(
        BASE + "/releases/" + row["id"] + "/plan",
        json={"expected_revision": row["revision"], "targets": ["win-x64"]},
    )
    assert response.status_code == 422 and "Range" in response.text
    mac = await release(actor.api, "2.0.0")
    payload, blockmap = files(monkeypatch)
    for role, data in [("payload", payload), ("blockmap", blockmap)]:
        await add(actor.api, mac, role, data, "mac-arm64")
        await worker.run_once(env.app)
    mac = (await actor.api.get(BASE + "/releases/" + mac["id"])).json()
    response = await actor.api.post(
        BASE + "/releases/" + mac["id"] + "/plan",
        json={"expected_revision": mac["revision"], "targets": ["mac-arm64"]},
    )
    assert response.status_code == 422
    artifact = await add(
        actor.api, mac, "installer", payload, "mac-arm64", sha512=checksum(b"wrong")
    )
    await worker.run_once(env.app)
    async with env.sessions() as db:
        stored = await db.get(ClientArtifact, UUID(artifact["id"]))
        assert stored.status == "failed" and stored.sha512 is None


async def test_storage_secrets_are_encrypted_and_locator_freezes_after_upload(env, monkeypatch):  # noqa: F811
    actor = await operator(env)
    monkeypatch.setattr(storage_router, "resolve", AsyncMock(return_value="8.8.8.8"))
    ident = str(uuid4())
    payload = {
        "expected_revision": 0,
        "name": "store",
        "endpoint": "https://s3.example.com",
        "region": "r1",
        "bucket": "bucket",
        "public_url": "https://files.example.com",
        "access_key": "test-access",
        "secret_key": "test-secret",
        "is_default": True,
    }
    result = await actor.api.put(BASE + "/storage/" + ident, json=payload)
    assert result.status_code == 200, result.text
    assert "test-secret" not in result.text and "access_key" not in result.text
    async with env.sessions() as db:
        stored = await db.get(ClientStorage, UUID(ident))
        assert "test-secret" not in stored.credentials
        assert env.provider.unseal(stored.credentials)["secret_key"] == "test-secret"
    row = await release(actor.api)
    item = await add(actor.api, row, "payload", b"data", url=None, storage_id=ident)
    async with env.sessions() as db:
        old_key = (await db.get(ClientArtifact, UUID(item["id"]))).object_key
    response = await actor.api.put(
        BASE + "/storage/" + ident, json={**payload, "expected_revision": 1, "bucket": "different"}
    )
    assert response.status_code == 409
    response = await actor.api.put(
        BASE + "/storage/" + ident,
        json={**payload, "expected_revision": 1, "secret_key": "rotated"},
    )
    assert response.status_code == 200

    current = (await actor.api.get(BASE + "/releases/" + row["id"])).json()
    removed = await actor.api.request(
        "DELETE",
        BASE + "/artifacts/" + item["id"],
        json={"expected_revision": current["revision"]},
    )
    assert removed.status_code == 200
    current = (await actor.api.get(BASE + "/releases/" + row["id"])).json()
    recreated = await actor.api.put(
        BASE + "/releases/" + row["id"] + "/artifacts/" + item["id"],
        json={
            "expected_revision": current["revision"],
            "target": "win-x64",
            "role": "payload",
            "filename": "app.exe",
            "size_bytes": 4,
            "storage_id": ident,
        },
    )
    assert recreated.status_code == 200, recreated.text
    async with env.sessions() as db:
        assert (await db.get(ClientArtifact, UUID(item["id"]))).object_key != old_key


async def test_expired_worker_lease_recovers_and_preserves_failures(env, monkeypatch):  # noqa: F811
    actor = await operator(env)
    row = await release(actor.api)
    payload, _ = files(monkeypatch)
    item = await add(actor.api, row, "payload", payload)
    async with env.sessions() as db:
        job = await db.scalar(select(ClientJob).where(ClientJob.artifact_id == UUID(item["id"])))
        job.status, job.lease_token, job.lease_until = (
            "running",
            uuid4(),
            now() - timedelta(minutes=1),
        )
        await db.commit()
    assert await worker.run_once(env.app)
    assert not await worker.run_once(env.app)
    result = (await actor.api.get(BASE + "/jobs?artifact_id=" + item["id"])).json()["items"][0]
    assert result["status"] == "succeeded" and result["processed_bytes"] == len(payload)


async def test_platform_cli_consent_is_separate_and_revoked_live(env, monkeypatch):  # noqa: F811
    actor = await operator(env)
    env.provider.settings.management_enabled = True
    env.provider.metadata = AsyncMock(
        return_value={"authorization_endpoint": env.provider.settings.oidc_issuer + "/auth"}
    )
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock())
    monkeypatch.setattr(
        NativeIdentity,
        "exchange",
        AsyncMock(
            return_value={
                "sub": actor.identity.subject,
                "auth_time": int(now().timestamp()),
                "name": actor.user.name,
                "email": actor.user.email,
            }
        ),
    )
    verifier = secrets.token_urlsafe(32)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=env.app), base_url="http://test"
    ) as cli:
        started = await cli.post(
            "/api/v1/management/login/start",
            json={
                "contract_version": 1,
                "authorization_version": 3,
                "target": "platform",
                "redirect_uri": "http://127.0.0.1:49161/actvero/cli/callback",
                "code_challenge": pkce(verifier),
                "device_name": "Platform CLI",
            },
        )
        assert started.status_code == 200, started.text
        attempt = started.json()
        proof = {"attempt_id": attempt["attempt_id"], "state": attempt["state"]}
        context = await actor.api.post("/api/v1/cli-authorization/context", json=proof)
        assert context.json()["target"] == "platform" and context.json()["organizations"] == []
        response = await actor.api.post(
            "/api/v1/cli-authorization/decision",
            json={
                **proof,
                "approve": True,
                "scope": "platform:read",
                "platform_permissions": ["releases.write"],
                "org_ids": [],
            },
        )
        assert response.status_code == 200, response.text
        exchanged = await cli.post(
            "/api/v1/management/login/exchange",
            json={**proof, "issuer": attempt["issuer"], "code_verifier": verifier, "code": "once"},
        )
        assert exchanged.status_code == 200, exchanged.text
        cli.headers["Authorization"] = "Bearer " + exchanged.json()["access_token"]
        prefix = "/api/v1/management/platform/client-distribution"
        assert (await cli.get(prefix + "/releases")).status_code == 200
        assert (await cli.get("/api/v1/management/organizations")).status_code == 403
        assert (await cli.post(prefix + "/storage/" + str(uuid4()) + "/test")).status_code == 403
        async with env.sessions() as db:
            (await db.get(PlatformOperator, actor.user.id)).status = "paused"
            await db.commit()
        assert (await cli.get(prefix + "/releases")).status_code == 403


async def test_semver_and_bounded_blockmaps():
    assert newer("1.0.0", "1.0.0-rc.2")
    assert newer("1.0.0-rc.10", "1.0.0-rc.2")
    assert not newer("1.0.0-rc.2", "1.0.0")
    assert not newer("1.0.0", "1.0.0")
    with pytest.raises(ValueError):
        DistributionSave(expected_revision=0, version="1.0.0-rc.1", channel="latest")
    for data in [b"not gzip", gzip.compress(b" " * (worker.MAX_BLOCKMAP + 1))]:
        with pytest.raises(HTTPException):
            worker.blockmap_metadata(data)


async def test_multipart_resume_and_lost_completion_response(env, monkeypatch):  # noqa: F811
    actor = await operator(env)
    monkeypatch.setattr(storage_router, "resolve", AsyncMock(return_value="8.8.8.8"))

    class Store:
        def __init__(self):
            self.remote = {}
            self.completed = False
            self.complete_calls = 0

        async def start(self, key):
            return "upload-one"

        async def call(self, operation, **kwargs):
            assert operation == "upload_part"
            n, body = kwargs["PartNumber"], kwargs["Body"]
            etag = '"' + hashlib.md5(body).hexdigest() + '"'
            self.remote[n] = (etag, len(body))
            return {"ETag": etag}

        async def parts(self, key, upload_id):
            return self.remote

        async def head(self, key):
            return {"ContentLength": 4} if self.completed else None

        async def complete(self, key, upload_id, parts):
            self.complete_calls += 1
            self.completed = True
            raise HTTPException(502, "simulated lost response")

    store = Store()
    env.app.state.client_store_factory = lambda *_: store
    storage_id = str(uuid4())
    response = await actor.api.put(
        BASE + "/storage/" + storage_id,
        json={
            "expected_revision": 0,
            "name": "multipart",
            "endpoint": "https://s3.example.com",
            "region": "r1",
            "bucket": "bucket",
            "public_url": "https://files.example.com",
            "access_key": "test-access",
            "secret_key": "test-secret",
        },
    )
    assert response.status_code == 200, response.text
    row = await release(actor.api)
    item = await add(actor.api, row, "payload", b"data", url=None, storage_id=storage_id)
    path = BASE + "/uploads/" + item["id"]
    assert (await actor.api.post(path + "/start")).json()["status"] == "uploading"
    assert (await actor.api.put(path + "/parts/1", content=b"too large")).status_code == 413
    part = await actor.api.put(path + "/parts/1", content=b"data")
    assert part.status_code == 200, part.text
    assert (await actor.api.post(path + "/complete")).status_code == 409
    ack = await actor.api.post(path + "/ack", json=part.json())
    assert ack.status_code == 200
    assert (await actor.api.get(path)).json()["parts"] == {"1": part.json()["etag"]}
    assert (await actor.api.post(path + "/complete")).status_code == 502
    assert (await actor.api.get(path)).json()["status"] == "completing"
    recovered = await actor.api.post(path + "/complete")
    assert recovered.status_code == 200 and recovered.json()["status"] == "completed"
    assert store.complete_calls == 1
    assert (await actor.api.post(path + "/complete")).status_code == 200
    assert (await actor.api.put(path + "/parts/1", content=b"data")).status_code == 409
    jobs = (await actor.api.get(BASE + "/jobs?artifact_id=" + item["id"])).json()["items"]
    assert len(jobs) == 1 and jobs[0]["status"] == "pending"


async def test_range_probe_requires_exact_identity_bytes(monkeypatch):
    from app.core.config import Settings

    for status, headers, body, expected in [
        (206, {"content-range": "bytes 0-0/123"}, b"x", True),
        (200, {}, b"x", False),
        (206, {"content-range": "bytes 0-0/124"}, b"x", False),
        (206, {"content-range": "bytes 0-0/123"}, b"xy", False),
    ]:

        @asynccontextmanager
        async def response(*args, status=status, headers=headers, body=body, **kwargs):
            yield httpx.Response(status, headers=headers, content=body)

        monkeypatch.setattr(network, "download", response)
        assert (
            await network.check_range(
                "https://files.example.com/app.exe", Settings(_env_file=None), 123
            )
            is expected
        )


async def test_abort_retry_accepts_missing_upload_but_preserves_provider_failure():
    store = ObjectStore.__new__(ObjectStore)
    store.bucket = "test-bucket"
    store.client = Mock()
    store.client.abort_multipart_upload.side_effect = ClientError(
        {"Error": {"Code": "NoSuchUpload"}}, "AbortMultipartUpload"
    )
    await store.abort("artifact", "upload")
    store.client.abort_multipart_upload.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "sensitive-provider-detail"}},
        "AbortMultipartUpload",
    )
    with pytest.raises(HTTPException) as error:
        await store.abort("artifact", "upload")
    assert error.value.status_code == 502
    assert "sensitive-provider-detail" not in str(error.value.detail)


async def test_private_default_storage_verifies_and_redirects_without_persisting_signed_urls(
    env,  # noqa: F811
    monkeypatch,
):
    actor = await operator(env)
    monkeypatch.setattr(storage_router, "resolve", AsyncMock(return_value="8.8.8.8"))
    storage_id = str(uuid4())
    result = await actor.api.put(
        "/api/v1/platform/object-storage/" + storage_id,
        json={
            "expected_revision": 0,
            "name": "private",
            "endpoint": "https://s3.example.com",
            "region": "r1",
            "bucket": "private-bucket",
            "is_default": True,
            "access_key": "test-access",
            "secret_key": "test-secret",
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["public_url"] == ""
    assert (await actor.api.get(BASE + "/storage")).json()["items"][0]["id"] == storage_id
    row = await release(actor.api)
    payload, blockmap = files(monkeypatch)
    signed = []

    class Store:
        async def sign_get(self, key):
            url = "https://s3.example.com/" + key + "?X-Amz-Signature=synthetic"
            signed.append(url)
            return url

    env.app.state.client_store_factory = lambda *_: Store()
    for role, data in [("payload", payload), ("blockmap", blockmap)]:
        item = await add(actor.api, row, role, data, url=None)
        assert item["storage_id"] == storage_id
        async with env.sessions() as db:
            artifact = await db.get(ClientArtifact, UUID(item["id"]))
            assert "/clients/1.0.0/win-x64/" in artifact.object_key
            artifact.status = "verifying"
            db.add(ClientJob(artifact_id=artifact.id, actor_id=actor.user.id))
            await db.commit()
        assert await worker.run_once(env.app)
    row = (await actor.api.get(BASE + "/releases/" + row["id"])).json()
    assert all(a["url"] is None and a["status"] == "ready" for a in row["artifacts"])
    response = await actor.api.post(
        BASE + "/releases/" + row["id"] + "/publish",
        json={"plan_id": (await plan(actor.api, row))["id"]},
    )
    assert response.status_code == 200, response.text
    async with env.sessions() as db:
        (await db.get(ClientStorage, UUID(storage_id))).enabled = False
        await db.commit()
    path = "/api/v1/client-artifacts/latest/win-x64/actvero-1.0.0-win-x64.exe"
    for _ in range(2):
        response = await actor.api.get(path, headers={"Range": "bytes=0-3"})
        assert response.status_code == 307
        assert response.headers["location"].startswith("https://s3.example.com/")
    assert len(signed) == 4
    async with env.sessions() as db:
        artifacts = (await db.scalars(select(ClientArtifact))).all()
        assert all(a.url is None for a in artifacts)


async def test_release_source_identity_and_legacy_draft_adoption(env):  # noqa: F811
    from app.modules.platform.download_models import ClientRelease

    actor = await operator(env)
    legacy_id = uuid4()
    async with env.sessions() as db:
        legacy = ClientRelease(
            id=legacy_id,
            version="1.0.0",
            release_date=now().date(),
            notes="keep",
            assets=[],
            status="draft",
            revision=1,
        )
        db.add(legacy)
        await db.commit()
    items = (await actor.api.get(BASE + "/releases?version=1.0.0")).json()["items"]
    assert len(items) == 1 and items[0]["legacy"] is True
    payload = {
        "expected_revision": 1,
        "version": "1.0.0",
        "notes": "keep",
        "source_commit": "a" * 40,
    }
    response = await actor.api.put(BASE + "/releases/" + str(legacy_id), json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["legacy"] is False and saved["source_commit"] == "a" * 40
    response = await actor.api.put(
        BASE + "/releases/" + str(legacy_id),
        json={**payload, "expected_revision": saved["revision"], "source_commit": "b" * 40},
    )
    assert response.status_code == 409
    assert (await actor.api.get(BASE + "/releases/" + str(legacy_id))).json()[
        "source_commit"
    ] == "a" * 40


async def test_upload_without_default_storage_fails_with_actionable_error(env):  # noqa: F811
    actor = await operator(env)
    row = await release(actor.api)
    response = await actor.api.put(
        BASE + "/releases/" + row["id"] + "/artifacts/" + str(uuid4()),
        json={
            "expected_revision": row["revision"],
            "target": "win-x64",
            "role": "payload",
            "filename": "app.exe",
            "size_bytes": 4,
        },
    )
    assert response.status_code == 422
    assert "默认对象存储" in response.text


async def test_windows_arm_release_has_independent_feed_download_and_blockmap(env, monkeypatch):  # noqa: F811
    actor = await operator(env)
    x64 = await verified(env, monkeypatch, actor, "1.0.0")
    await actor.api.post(
        BASE + "/releases/" + x64["id"] + "/publish",
        json={"plan_id": (await plan(actor.api, x64))["id"]},
    )
    arm = await verified(env, monkeypatch, actor, "2.0.0", target="win-arm64")
    response = await actor.api.post(
        BASE + "/releases/" + arm["id"] + "/publish",
        json={"plan_id": (await plan(actor.api, arm, ["win-arm64"]))["id"]},
    )
    assert response.status_code == 200, response.text
    feed = await actor.api.get("/api/v1/client-updates/actvero/win-arm64/latest.yml")
    assert feed.status_code == 200 and "actvero-2.0.0-win-arm64.exe" in feed.text
    x64_feed = await actor.api.get("/api/v1/client-updates/actvero/win-x64/latest.yml")
    assert x64_feed.status_code == 200 and "actvero-1.0.0-win-x64.exe" in x64_feed.text
    async with env.sessions() as db:
        from app.modules.platform.download_models import ClientRelease

        saved = await db.get(ClientRelease, UUID(arm["id"]))
        assert saved.assets[0]["platform"] == "windows"
        assert saved.assets[0]["architecture"] == "arm64"
    for extension in [".exe", ".exe.blockmap"]:
        file = await actor.api.get(
            "/api/v1/client-artifacts/latest/win-arm64/actvero-2.0.0-win-arm64" + extension
        )
        assert file.status_code == 307
