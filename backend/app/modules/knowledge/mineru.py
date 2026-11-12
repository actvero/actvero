"""Official MinerU API; account-scoped cooldowns and durable submission identity."""

import json
from datetime import timedelta
from typing import Any

import httpx2
from fastapi import HTTPException, Request
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbound import PinnedTransport, origin, resolve
from app.modules.auth.service import now, provider
from app.modules.knowledge.models import KnowledgeGeneration, ParserCredential
from app.modules.knowledge.parsing import MAX_FILE
from app.modules.object_storage.network import download
from app.modules.object_storage.validation import https_url
from app.modules.tenants.models import Tenant

BASE = "https://mineru.net"


class ParserWait(Exception):
    def __init__(self, message: str, seconds: int = 15):
        self.message, self.seconds = message, seconds


class SubmissionUnknown(Exception):
    pass


async def credential(db: AsyncSession, tenant_id: Any) -> ParserCredential:
    await db.scalar(select(Tenant.id).where(Tenant.id == tenant_id).with_for_update())
    row = await db.scalar(
        select(ParserCredential)
        .where(
            ParserCredential.tenant_id == tenant_id,
            ParserCredential.enabled.is_(True),
            or_(
                ParserCredential.cooldown_until.is_(None), ParserCredential.cooldown_until <= now()
            ),
        )
        .order_by(ParserCredential.last_used_at.asc().nullsfirst(), ParserCredential.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        raise ParserWait("等待可用的 MinerU 凭据，请在默认配置中添加或检查 Key", 30)
    row.last_used_at = now()
    await db.execute(
        update(ParserCredential)
        .where(
            ParserCredential.tenant_id == tenant_id,
            ParserCredential.account == row.account,
        )
        .values(cooldown_until=now() + timedelta(seconds=1))
    )
    await db.commit()
    return row


async def api(
    request: Request,
    db: AsyncSession,
    key: ParserCredential,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    secret = provider(request).unseal(key.secret)["key"]
    try:
        async with httpx2.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(
                "POST" if payload is not None else "GET",
                BASE + path,
                headers={"Authorization": "Bearer " + secret},
                json=payload,
            )
        if response.status_code == 429:
            retry = response.headers.get("retry-after", "60")
            seconds = min(3600, max(5, int(retry))) if retry.isdigit() else 60
            await db.execute(
                update(ParserCredential)
                .where(
                    ParserCredential.tenant_id == key.tenant_id,
                    ParserCredential.account == key.account,
                )
                .values(
                    cooldown_until=now() + timedelta(seconds=seconds),
                    error="官方账号限流，等待恢复",
                )
            )
            await db.commit()
            raise ParserWait("MinerU 账号限流，自动等待或切换可用账号", 1)
        if response.status_code in {401, 403}:
            key.enabled, key.error = False, "凭据无效或无权访问，请更新 Key"
            await db.commit()
            raise HTTPException(422, key.error)
        if response.status_code != 200:
            if payload is not None and response.status_code >= 500:
                raise SubmissionUnknown()
            raise ParserWait("MinerU 服务暂不可用，等待重试", 30)
        if len(response.content) > 4 * 1024 * 1024:
            raise HTTPException(502, "MinerU 返回的任务信息过大")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError()
        if body.get("code") != 0:
            # Never display upstream messages, which may contain signed URLs or credentials.
            if str(body.get("code")) in {"-60005", "-60006", "-60007"}:
                raise HTTPException(422, "MinerU 拒绝文件，请检查格式、大小和页数")
            raise HTTPException(502, "MinerU 未接受请求，请检查账号额度和文件要求")
        result = body.get("data")
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (httpx2.HTTPError, ValueError, TypeError):
        if payload is not None:
            raise SubmissionUnknown() from None
        raise ParserWait("暂未取得 MinerU 任务状态，稍后继续查询", 15) from None


async def upload(url: str, data: bytes) -> None:
    https_url(url)

    async def resolver(value: str) -> str:
        return await resolve(value, [])

    try:
        async with httpx2.AsyncClient(
            transport=PinnedTransport(origin(url), resolver, max_bytes=MAX_FILE + 1),
            timeout=90,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.put(url, content=data)
            if response.status_code not in {200, 201, 204}:
                raise HTTPException(502, "MinerU 文件上传未完成，请重试文档")
    except httpx2.HTTPError:
        raise ParserWait("文件上传暂未完成，将继续上传原任务", 15) from None


async def result(request: Request, url: str) -> bytes:
    content = bytearray()
    async with download(url, provider(request).settings) as response:
        async for part in response.aiter_bytes():
            content.extend(part)
            if len(content) > 100 * 1024 * 1024:
                raise HTTPException(422, "MinerU 解析结果超过 100 MiB，请拆分文档")
    return bytes(content)


async def parse(
    request: Request,
    db: AsyncSession,
    generation: KnowledgeGeneration,
    tenant_id: Any,
    filename: str,
    data: bytes,
) -> bytes:
    if generation.submission_pending:
        raise SubmissionUnknown()
    if not generation.batch_id:
        key = await credential(db, tenant_id)
        generation.credential_id = key.id
        generation.submission_pending = True
        await db.commit()
        try:
            response = await api(
                request,
                db,
                key,
                "/api/v4/file-urls/batch",
                {
                    "files": [{"name": filename, "data_id": str(generation.id)}],
                    "model_version": "vlm",
                    "enable_table": True,
                    "enable_formula": True,
                },
            )
        except (ParserWait, HTTPException):
            generation.submission_pending = False
            await db.commit()
            raise
        batch_id, urls = response.get("batch_id"), response.get("file_urls")
        if (
            not isinstance(batch_id, str)
            or not isinstance(urls, list)
            or len(urls) != 1
            or not isinstance(urls[0], str)
        ):
            raise SubmissionUnknown()
        generation.batch_id = batch_id
        generation.upload_url = provider(request).seal({"url": urls[0]})
        generation.submission_pending = False
        await db.commit()
    stored_key = await db.get(ParserCredential, generation.credential_id)
    if stored_key is None:
        raise HTTPException(422, "解析任务凭据已移除")
    if generation.upload_url:
        await upload(provider(request).unseal(generation.upload_url)["url"], data)
        generation.upload_url = None
        await db.commit()
    response = await api(
        request, db, stored_key, "/api/v4/extract-results/batch/" + generation.batch_id
    )
    entries = response.get("extract_result", [])
    entry = next((e for e in entries if e.get("data_id") == str(generation.id)), None)
    if not entry:
        raise ParserWait("等待 MinerU 识别文件", 10)
    if entry.get("state") == "failed":
        raise HTTPException(422, "MinerU 解析失败，请检查文件后重试")
    if entry.get("state") != "done":
        raise ParserWait("MinerU 正在解析", 10)
    url = entry.get("full_zip_url")
    if not isinstance(url, str):
        raise HTTPException(502, "MinerU 未返回解析产物")
    try:
        return await result(request, url)
    except (httpx2.HTTPError, json.JSONDecodeError):
        raise ParserWait("解析完成，等待下载结果", 15) from None
