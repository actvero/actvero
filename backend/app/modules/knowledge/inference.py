"""Server-created, resource-bound calls reuse model authorization and settlement."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now
from app.modules.knowledge.models import KnowledgeBase, KnowledgeSettings
from app.modules.knowledge.service import visible
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.inference_schemas import (
    EmbeddingInput,
    EmbeddingOutput,
    RerankInput,
    RerankOutput,
)
from app.modules.llm.models import CatalogModel
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor, membership_state, with_departments
from app.modules.tenants.models import Tenant
from app.modules.users.models import User


@dataclass(frozen=True)
class KnowledgeInvocation:
    tenant_id: UUID
    base_id: UUID
    initiator_id: UUID
    model_id: UUID
    created_at: datetime
    purpose: Literal["index", "search"]
    operation: Literal["embedding", "rerank"]


async def model_actor(request: Request, db: AsyncSession, resource: str | None) -> BusinessActor:
    context = request.state.knowledge_invocation
    if not isinstance(context, KnowledgeInvocation):
        raise HTTPException(403, "知识库执行身份无效")
    if resource and resource != "llm:" + str(context.model_id):
        raise HTTPException(403, "知识库调用范围不符")
    base = await db.get(KnowledgeBase, context.base_id, populate_existing=True)
    tenant = await db.get(Tenant, context.tenant_id, populate_existing=True)
    settings = await db.get(KnowledgeSettings, context.tenant_id, populate_existing=True)
    caller = await db.get(Membership, context.initiator_id, populate_existing=True)
    if (
        not base
        or base.tenant_id != context.tenant_id
        or not settings
        or not caller
        or caller.tenant_id != context.tenant_id
        or membership_state(tenant, caller, context.created_at)
    ):
        raise HTTPException(403, "知识库或任务发起人的权限已变化")
    caller_user = await db.get(User, caller.user_id)
    assert tenant is not None and caller_user is not None
    caller_actor = await with_departments(db, BusinessActor(caller_user, caller, tenant))
    if (
        not visible(base, caller_actor)
        or context.purpose == "index"
        and caller.role != "administrator"
    ):
        raise HTTPException(403, "知识库访问权限已变化")
    allowed = (
        base.embedding_profile.get("model_id")
        if context.operation == "embedding"
        else str(settings.rerank_model_id)
        if context.purpose == "search" and settings.rerank_enabled
        else None
    )
    if str(context.model_id) != allowed:
        raise HTTPException(409, "知识库模型配置已变化，请重试")
    if context.operation == "embedding":
        model = await db.get(CatalogModel, context.model_id, populate_existing=True)
        config = (
            CatalogInput.model_validate(model.configuration).for_operation("embedding")
            if model
            else None
        )
        profile = base.embedding_profile
        if (
            not config
            or config.retrieval.embedding_space != profile.get("embedding_space")
            or config.retrieval.dimensions != profile.get("dimensions")
        ):
            raise HTTPException(409, "向量空间或维度已变化，请使用匹配的知识库")
    executor = (
        await db.get(Membership, settings.executor_member_id, populate_existing=True)
        if settings.executor_member_id
        else None
    )
    if (
        not executor
        or executor.tenant_id != context.tenant_id
        or executor.role != "administrator"
        or membership_state(tenant, executor, settings.authorized_at)
    ):
        raise HTTPException(403, "知识库模型执行授权已失效，请管理员重新保存默认配置")
    user = await db.get(User, executor.user_id)
    assert user is not None
    return await with_departments(db, BusinessActor(user, executor, tenant))


async def invoke(
    request: Request,
    db: AsyncSession,
    base: KnowledgeBase,
    initiator_id: UUID,
    model_id: UUID,
    body: EmbeddingInput | RerankInput,
    *,
    purpose: Literal["index", "search"],
    created_at: datetime | None = None,
) -> EmbeddingOutput | RerankOutput:
    from app.modules.llm.runtime import invoke as model_invoke

    child = Request({"type": "http", "app": request.app, "headers": [], "state": {}})
    child.state.knowledge_invocation = KnowledgeInvocation(
        base.tenant_id,
        base.id,
        initiator_id,
        model_id,
        created_at or now(),
        purpose,
        "embedding" if isinstance(body, EmbeddingInput) else "rerank",
    )
    return await model_invoke(child, db, model_id, body)
