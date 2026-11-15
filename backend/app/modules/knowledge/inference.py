"""Authorize organization model calls and independently verify the knowledge caller."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now
from app.modules.integrations import service as integrations
from app.modules.knowledge.models import KnowledgeBase
from app.modules.knowledge.service import KnowledgeActor, can_manage, effective_retrieval, visible
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
    initiator_id: UUID | None
    model_id: UUID
    created_at: datetime
    purpose: Literal["index", "search"]
    operation: Literal["embedding", "rerank"]
    application_key_id: UUID | None = None


async def authorize_invocation(
    request: Request, db: AsyncSession, resource: str | None
) -> KnowledgeActor:
    context = request.state.knowledge_invocation
    if not isinstance(context, KnowledgeInvocation):
        raise HTTPException(403, "知识库执行身份无效")
    if resource is not None and resource != "llm:" + str(context.model_id):
        raise HTTPException(403, "知识库调用范围不符")
    base = await db.get(KnowledgeBase, context.base_id, populate_existing=True)
    tenant = await db.get(Tenant, context.tenant_id, populate_existing=True)
    if not base or base.tenant_id != context.tenant_id or not tenant or not tenant.active:
        raise HTTPException(403, "知识库或组织不可用")
    caller_actor: KnowledgeActor
    if context.application_key_id is not None:
        caller_actor = await integrations.bound(
            request,
            db,
            context.application_key_id,
            "knowledge_write" if context.purpose == "index" else "knowledge",
            admitted_job=context.purpose == "index",
        )
    else:
        caller = await db.get(Membership, context.initiator_id) if context.initiator_id else None
        if (
            not caller
            or caller.tenant_id != context.tenant_id
            or membership_state(tenant, caller, context.created_at)
        ):
            raise HTTPException(403, "任务发起人的权限已变化")
        caller_user = await db.get(User, caller.user_id)
        assert caller_user is not None
        caller_actor = await with_departments(db, BusinessActor(caller_user, caller, tenant))
    if not visible(base, caller_actor) or (
        context.purpose == "index" and not can_manage(base, caller_actor)
    ):
        raise HTTPException(403, "知识库访问权限已变化")
    policy = await effective_retrieval(db, base)
    allowed = None
    if context.operation == "embedding" and (
        context.purpose == "index" or policy.mode != "keyword"
    ):
        allowed = base.embedding_profile.get("model_id")
    elif context.operation == "rerank" and context.purpose == "search" and policy.rerank_model_id:
        allowed = str(policy.rerank_model_id)
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
    return caller_actor


async def invoke(
    request: Request,
    db: AsyncSession,
    base: KnowledgeBase,
    initiator_id: UUID | None,
    model_id: UUID,
    body: EmbeddingInput | RerankInput,
    *,
    purpose: Literal["index", "search"],
    created_at: datetime | None = None,
    application_key_id: UUID | None = None,
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
        application_key_id,
    )
    return await model_invoke(child, db, model_id, body)
