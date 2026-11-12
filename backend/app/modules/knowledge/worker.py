"""Bounded job phases with database leases; uncertain paid requests are not replayed."""

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now
from app.modules.knowledge import mineru
from app.modules.knowledge.inference import invoke
from app.modules.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeGeneration,
)
from app.modules.knowledge.parsing import REMOTE_TYPES, local_parse, mineru_parse, split_blocks
from app.modules.knowledge.schemas import Chunking
from app.modules.knowledge.service import visible
from app.modules.llm.inference_schemas import EmbeddingInput, EmbeddingOutput
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor, membership_state, with_departments
from app.modules.tenants.models import Tenant
from app.modules.users.models import User

ACTIVE = {"queued", "parsing", "chunking", "indexing", "waiting"}


async def phase(request: Request, db: AsyncSession, job: KnowledgeGeneration) -> None:
    doc = await db.get(KnowledgeDocument, job.document_id, populate_existing=True)
    base = await db.get(KnowledgeBase, doc.base_id) if doc else None
    if not doc or not base or base.archived or doc.deleted_at or doc.latest_generation_id != job.id:
        job.status = "cancelled"
        return
    member = await db.get(Membership, job.actor_member_id)
    tenant = await db.get(Tenant, base.tenant_id)
    if (
        not member
        or member.tenant_id != base.tenant_id
        or member.role != "administrator"
        or membership_state(tenant, member, job.created_at)
    ):
        raise HTTPException(403, "任务发起人的组织权限已失效，请管理员重新处理")
    user = await db.get(User, member.user_id)
    assert user is not None and tenant is not None
    actor = await with_departments(db, BusinessActor(user, member, tenant))
    if not visible(base, actor):
        raise HTTPException(403, "知识库访问权限已失效")
    if job.inference_pending:
        raise mineru.SubmissionUnknown()
    await db.refresh(job, ["blocks", "raw_parse"])
    if not job.blocks:
        job.status, job.error = "parsing", ""
        await db.commit()
        await db.refresh(doc, ["data"])
        ext = "." + doc.filename.rsplit(".", 1)[-1].lower()
        if ext in REMOTE_TYPES:
            data = await mineru.parse(request, db, job, base.tenant_id, doc.filename, doc.data)
            job.raw_parse, job.blocks = await asyncio.to_thread(mineru_parse, data)
        else:
            job.blocks = await asyncio.to_thread(local_parse, doc.filename, doc.data)
            job.raw_parse = {"format": "local-structured-v1"}
        job.status = "chunking"
        return
    count = await db.scalar(
        select(func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.generation_id == job.id)
    )
    if not count:
        hard_limit = min(
            10000,
            job.embedding_profile.get("max_input_characters", 10000),
            job.embedding_profile.get("context_window") or 10000,
        )
        chunks = split_blocks(
            job.blocks, Chunking.model_validate(job.chunking), hard_limit=hard_limit
        )
        db.add_all(
            KnowledgeChunk(generation_id=job.id, sequence=i + 1, content=text, sources=sources)
            for i, (text, sources) in enumerate(chunks)
        )
        job.status = "indexing"
        return
    if not job.embedding_profile:
        job.status, job.error = "unconfigured", "尚未配置默认向量模型，当前可使用关键词检索"
        doc.active_generation_id = job.id
        job.finished_at = now()
        return
    chunk = await db.scalar(
        select(KnowledgeChunk)
        .where(KnowledgeChunk.generation_id == job.id, KnowledgeChunk.vector.is_(None))
        .order_by(KnowledgeChunk.sequence)
        .limit(1)
    )
    if chunk:
        job.status, job.error, job.inference_pending = "indexing", "", True
        await db.commit()
        profile = job.embedding_profile
        output = await invoke(
            request,
            db,
            base,
            member.id,
            UUID(profile["model_id"]),
            EmbeddingInput(
                model=profile["slug"], input=chunk.content, dimensions=profile["dimensions"]
            ),
            purpose="index",
            created_at=job.created_at,
        )
        if (
            not isinstance(output, EmbeddingOutput)
            or len(output.data) != 1
            or len(output.data[0].embedding) != profile["dimensions"]
        ):
            raise HTTPException(502, "向量模型返回维度不匹配，请核对模型配置")
        chunk.vector = output.data[0].embedding
        job.inference_pending = False
        return
    # Publish the complete generation atomically; the previous index stays readable during rebuild.
    await db.refresh(doc)
    if doc.latest_generation_id == job.id and not doc.deleted_at:
        doc.active_generation_id = job.id
        job.status, job.error, job.finished_at = "ready", "", now()
    else:
        job.status = "cancelled"


async def tick(app: FastAPI) -> bool:
    async with app.state.database.sessions() as db:
        job = await db.scalar(
            select(KnowledgeGeneration)
            .where(
                KnowledgeGeneration.status.in_(ACTIVE),
                KnowledgeGeneration.next_run_at <= now(),
                or_(
                    KnowledgeGeneration.lease_until.is_(None),
                    KnowledgeGeneration.lease_until < now(),
                ),
            )
            .order_by(KnowledgeGeneration.next_run_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return False
        token = uuid4()
        job.lease_token, job.lease_until = token, now() + timedelta(minutes=5)
        await db.commit()
        ident = job.id
        try:
            await asyncio.wait_for(
                phase(Request({"type": "http", "app": app, "headers": []}), db, job), 180
            )
        except mineru.ParserWait as exc:
            job.status, job.error = "waiting", exc.message
            job.next_run_at = now() + timedelta(seconds=exc.seconds)
        except mineru.SubmissionUnknown:
            job.status, job.error = (
                "uncertain",
                "外部任务结果尚不确定，已停止自动重试；请核对服务任务或模型调用记录后重新处理",
            )
        except (HTTPException, ValueError) as exc:
            job.status = "uncertain" if job.inference_pending else "failed"
            # Runtime and upstream errors may contain private provider details.
            job.error = (
                "文件内容或解析结构无效，请检查格式后重试"
                if isinstance(exc, ValueError)
                else "处理未完成，请检查解析凭据、模型配置、额度及调用记录后重试"
            )
        except Exception:
            await db.rollback()
            job = await db.get(KnowledgeGeneration, ident)
            assert job is not None
            job.status = (
                "uncertain" if job.inference_pending or job.submission_pending else "failed"
            )
            job.error = "处理暂未完成，请核对任务后重试"
        # Every phase is bounded below the lease duration.
        if job.lease_token == token:
            job.lease_token, job.lease_until = None, None
            await db.commit()
    return True


async def monitor(app: FastAPI) -> None:
    while True:
        try:
            processed = await tick(app)
        except Exception:
            processed = False
        await asyncio.sleep(0.1 if processed else 2)
