"""Durable, leased verification jobs. Network failures never publish partial releases."""

import asyncio
import base64
import hashlib
import json
import logging
import tempfile
import zlib
from datetime import timedelta
from typing import BinaryIO
from uuid import UUID, uuid4

import httpx2
from fastapi import FastAPI, HTTPException
from sqlalchemy import or_, select, update

from app.modules.auth.service import now
from app.modules.client_distribution.models import ClientArtifact, ClientJob, ClientStorage
from app.modules.client_distribution.storage import ObjectStore
from app.modules.object_storage.network import check_range, download
from app.modules.platform.download_models import ClientRelease
from app.modules.tenants.models import Installation, PlatformOperator

logger = logging.getLogger(__name__)
MAX_FILE = 20_000_000_000
MAX_BLOCKMAP = 8_000_000


def blockmap_metadata(data: bytes) -> dict[str, object]:
    try:
        inflater = zlib.decompressobj(47)  # gzip / zlib, with an explicit expansion limit
        raw = inflater.decompress(data, MAX_BLOCKMAP + 1)
        if len(raw) > MAX_BLOCKMAP or not inflater.eof or inflater.unused_data:
            raise ValueError()
        document = json.loads(raw)
        if document.get("version") != "2" or not isinstance(document.get("files"), list):
            raise ValueError()
        end = 0
        for file in document["files"]:
            sizes, checksums = file["sizes"], file["checksums"]
            offset = file["offset"]
            if (
                type(offset) is not int
                or offset != end
                or not sizes
                or len(sizes) != len(checksums)
            ):
                raise ValueError()
            if any(type(s) is not int or not 0 < s <= MAX_FILE for s in sizes):
                raise ValueError()
            if any(not isinstance(c, str) or not 1 <= len(c) <= 128 for c in checksums):
                raise ValueError()
            end += sum(sizes)
        if not 0 < end <= MAX_FILE:
            raise ValueError()
        return {"payload_size": end, "blockmap_version": "2"}
    except (ValueError, TypeError, KeyError, AttributeError, zlib.error):
        raise HTTPException(
            422, "blockmap 格式无效或超过大小限制，请使用构建工具生成的配套文件"
        ) from None


async def heartbeat(app: FastAPI, ident: UUID, token: UUID) -> None:
    while True:
        await asyncio.sleep(20)
        async with app.state.database.sessions() as db:
            await db.execute(
                update(ClientJob)
                .where(
                    ClientJob.id == ident,
                    ClientJob.lease_token == token,
                    ClientJob.status == "running",
                )
                .values(lease_until=now() + timedelta(minutes=2))
            )
            await db.commit()


async def read_file(
    app: FastAPI, job_id: UUID, token: UUID, url: str, *, limit: int, output: BinaryIO | None = None
) -> tuple[int, str, str, bytes]:
    settings = app.state.identity_provider.settings
    total = 0
    sha512, sha256 = hashlib.sha512(), hashlib.sha256()
    small = bytearray()
    reported = 0
    async with download(url, settings) as response:
        if response.status_code != 200:
            raise HTTPException(422, "完整文件下载返回了部分内容")
        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
            total += len(chunk)
            if total > limit:
                raise HTTPException(422, "文件超过声明大小或允许上限")
            sha512.update(chunk)
            sha256.update(chunk)
            if len(small) <= MAX_BLOCKMAP:
                small.extend(chunk)
            if output:
                await asyncio.to_thread(output.write, chunk)
            if total - reported >= 16 * 1024 * 1024:
                async with app.state.database.sessions() as db:
                    await db.execute(
                        update(ClientJob)
                        .where(ClientJob.id == job_id, ClientJob.lease_token == token)
                        .values(processed_bytes=total)
                    )
                    await db.commit()
                reported = total
    if not total:
        raise HTTPException(422, "文件为空")
    return total, base64.b64encode(sha512.digest()).decode(), sha256.hexdigest(), bytes(small)


async def process(app: FastAPI, job: ClientJob, token: UUID) -> None:
    async with app.state.database.sessions() as db:
        artifact = await db.get(ClientArtifact, job.artifact_id)
        operator = await db.get(PlatformOperator, job.actor_id)
        if not artifact or artifact.published_at or not operator or operator.status != "active":
            raise HTTPException(403, "文件状态或操作人员权限已改变，请重新检查")
        profile = await db.get(ClientStorage, artifact.storage_id) if artifact.storage_id else None
    url = artifact.url or ""
    key = artifact.object_key
    limit = min(
        artifact.size_bytes or MAX_FILE, MAX_BLOCKMAP if artifact.role == "blockmap" else MAX_FILE
    )
    if artifact.source == "mirror":
        if not profile or not profile.enabled or not artifact.source_url_ciphertext:
            raise HTTPException(422, "转存所需存储配置不可用")
        source = app.state.identity_provider.unseal(artifact.source_url_ciphertext)["url"]
        factory = getattr(app.state, "client_store_factory", ObjectStore)
        store = factory(profile, app.state.identity_provider.unseal(profile.credentials))
        # Every lease writes a new object. A worker whose lease was stolen cannot
        # overwrite the bytes selected by a newer, successfully published attempt.
        key = f"{profile.prefix}/{artifact.id}/{token}/{artifact.filename}"
        with tempfile.TemporaryFile() as temp:
            source_size, source_hash, _, _ = await read_file(
                app, job.id, token, source, limit=limit, output=temp
            )
            if artifact.size_bytes and source_size != artifact.size_bytes:
                raise HTTPException(422, "来源文件大小与声明不符")
            if artifact.expected_sha512 and source_hash != artifact.expected_sha512:
                raise HTTPException(422, "来源文件 SHA-512 与声明不符")
            temp.seek(0)
            await store.put_large(key, temp)
        url = f"{profile.public_url}/{key}"
    stored_url = (
        f"{profile.public_url}/{key}" if profile and profile.public_url and key else artifact.url
    )
    if profile and key and not profile.public_url:
        factory = getattr(app.state, "client_store_factory", ObjectStore)
        url = await factory(
            profile, app.state.identity_provider.unseal(profile.credentials)
        ).sign_get(key)
    size, sha512, sha256, small = await read_file(app, job.id, token, url, limit=limit)
    if artifact.size_bytes and size != artifact.size_bytes:
        raise HTTPException(422, "下载文件大小与声明不符")
    if artifact.expected_sha512 and sha512 != artifact.expected_sha512:
        raise HTTPException(422, "下载文件 SHA-512 与声明不符")
    validation = blockmap_metadata(small) if artifact.role == "blockmap" else {}
    ranges = (
        await check_range(url, app.state.identity_provider.settings, size)
        if artifact.role == "payload"
        else False
    )
    async with app.state.database.sessions() as db:
        await db.scalar(select(Installation).where(Installation.id == 1).with_for_update())
        current = await db.scalar(select(ClientJob).where(ClientJob.id == job.id).with_for_update())
        if not current or current.lease_token != token or current.status != "running":
            return
        operator = await db.get(PlatformOperator, job.actor_id)
        if not operator or operator.status != "active":
            raise HTTPException(403, "操作人员的平台权限已撤销")
        artifact = await db.get(ClientArtifact, job.artifact_id, populate_existing=True)
        if not artifact or artifact.published_at:
            raise HTTPException(409, "文件状态已改变")
        release = await db.scalar(
            select(ClientRelease).where(ClientRelease.id == artifact.release_id).with_for_update()
        )
        assert release
        artifact.url, artifact.object_key = stored_url, key
        artifact.size_bytes, artifact.sha512, artifact.sha256 = size, sha512, sha256
        artifact.status, artifact.validation, artifact.range_supported, artifact.error = (
            "ready",
            validation,
            ranges,
            None,
        )
        current.status, current.processed_bytes, current.error, current.lease_until = (
            "succeeded",
            size,
            None,
            None,
        )
        release.revision += 1
        release.updated_at = now()
        await db.commit()


async def run_once(app: FastAPI) -> bool:
    async with app.state.database.sessions() as db:
        job = await db.scalar(
            select(ClientJob)
            .where(
                or_(
                    ClientJob.status == "pending",
                    (ClientJob.status == "running") & (ClientJob.lease_until < now()),
                )
            )
            .order_by(ClientJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return False
        token = uuid4()
        job.status, job.lease_token, job.lease_until = (
            "running",
            token,
            now() + timedelta(minutes=2),
        )
        await db.commit()
    pulse = asyncio.create_task(heartbeat(app, job.id, token))
    error = None
    try:
        async with asyncio.timeout(7200):
            await process(app, job, token)
    except HTTPException as exc:
        error = str(exc.detail)[:500]
    except (httpx2.HTTPError, OSError, TimeoutError):
        error = "文件传输未完成，请检查下载地址、存储连接和剩余磁盘空间后重试"
    except Exception:
        # Do not log exception text: network errors can contain source URL secrets.
        logger.error("Client artifact job failed; job_id=%s", job.id)
        error = "文件处理失败，请联系平台维护人员并提供任务编号"
    finally:
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
    if error:
        async with app.state.database.sessions() as db:
            current = await db.scalar(
                select(ClientJob).where(ClientJob.id == job.id).with_for_update()
            )
            if current and current.lease_token == token:
                current.status, current.error, current.lease_until = "failed", error, None
                artifact = await db.get(ClientArtifact, current.artifact_id)
                if artifact and not artifact.published_at:
                    artifact.status, artifact.error = "failed", error
                await db.commit()
    return True


async def monitor(app: FastAPI) -> None:
    while True:
        try:
            if await run_once(app):
                continue
        except Exception:
            logger.error("Client artifact worker unavailable; retrying")
        await asyncio.sleep(5)
