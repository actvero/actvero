"""Live organization authorization and durable at-most-once mutation dispatch."""

import hashlib
import hmac
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now, provider
from app.modules.desktop.errors import fail
from app.modules.management import service
from app.modules.management.models import ManagementCommand
from app.modules.management.schemas import ResourceResult

T = TypeVar("T")


async def read_resource[T](
    request: Request,
    db: AsyncSession,
    org_id: UUID,
    operation: Callable[..., Awaitable[T]],
    **kwargs: Any,
) -> ResourceResult[T]:
    who = await service.actor(request, db)
    actor, organization = await service.organization(request, db, who, org_id, require_admin=True)
    result = await operation(actor=actor, request=request, db=db, **kwargs)
    await db.commit()
    return ResourceResult(organization=organization, result=result)


async def mutate_resource[T](
    request: Request,
    db: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    operation: Callable[..., Awaitable[T]],
    retain_result: bool = True,
    **kwargs: Any,
) -> ResourceResult[T]:
    who = await service.actor(request, db)
    actor, organization = await service.organization(
        request, db, who, org_id, require_admin=True, write=True
    )
    key = provider(request).settings.session_encryption_key
    if key is None:
        fail(503, "management_unavailable", "管理写入尚未配置")
    identity = request.method + " " + request.url.path + "?" + request.url.query
    fingerprint = hmac.new(
        key.get_secret_value().encode(),
        identity.encode() + b"\0" + await request.body(),
        hashlib.sha256,
    ).hexdigest()
    command_key = (org_id, actor.user.id, request_id)
    previous = await db.get(ManagementCommand, command_key, populate_existing=True)
    if previous:
        if not hmac.compare_digest(previous.fingerprint, fingerprint):
            fail(409, "command_conflict", "此请求编号已用于其他内容，请重新核对")
        if previous.status == "succeeded" and previous.result is not None:
            if not retain_result:
                fail(
                    409,
                    "command_result_not_retained",
                    "此请求已执行，结果正文不保存；请查询回执，不会重复执行",
                )
            return ResourceResult[T].model_validate(previous.result)
        fail(
            409, "command_unconfirmed", "原请求正在执行或结果未确认，请查询原请求回执；不会自动重发"
        )
    receipt = ManagementCommand(
        tenant_id=org_id,
        user_id=actor.user.id,
        request_id=request_id,
        fingerprint=fingerprint,
        operation=identity.split("?", 1)[0],
        status="pending",
        created_at=now(),
    )
    db.add(receipt)
    # Save intent before network discovery or any domain service that can commit.
    await db.commit()
    try:
        # Revalidate after the commit released locks. Membership changes share this tenant lock.
        who = await service.actor(request, db)
        actor, organization = await service.organization(
            request, db, who, org_id, require_admin=True, write=True
        )
        result = await operation(actor=actor, request=request, db=db, **kwargs)
        response: ResourceResult[T] = ResourceResult(
            organization=organization, result=result, request_id=request_id
        )
        receipt.status, receipt.result, receipt.finished_at = (
            "succeeded",
            jsonable_encoder(response)
            if retain_result
            else {
                "organization": organization.model_dump(mode="json"),
                "request_id": str(request_id),
                "result": {"result_retained": False},
            },
            now(),
        )
        await db.commit()
        return response
    except Exception:
        await db.rollback()
        # Unknown is deliberately conservative: some network operations commit audit evidence.
        current = await db.get(ManagementCommand, command_key)
        if current and current.status == "pending":
            current.status, current.finished_at = "unknown", now()
            await db.commit()
        raise
