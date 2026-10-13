"""Structured operation metadata only; never persist arguments, results or raw exceptions."""

import time
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp.credentials import owner
from app.modules.mcp.models import McpActivity, McpService
from app.modules.members.service import BusinessActor


def failure(exc: Exception) -> tuple[str, str, str]:
    if isinstance(exc, TimeoutError) or isinstance(exc, HTTPException) and exc.status_code == 504:
        return "timeout", "timeout", "上游响应超时；未自动重试业务调用"
    if isinstance(exc, HTTPException):
        if exc.status_code in (401, 403):
            return "failed", "access_denied", "当前身份没有此操作权限"
        if exc.status_code == 409:
            return "failed", "configuration_required", "连接凭据或能力定义需要更新"
        if exc.status_code == 422:
            return "failed", "invalid_arguments", "参数不符合能力定义"
    return "failed", "upstream_unavailable", "上游请求未确认成功，请检查服务和凭据"


def add_activity(
    db: AsyncSession,
    request: Request,
    service: McpService,
    actor: BusinessActor,
    category: Literal["call", "connection"],
    operation: str,
    started: float,
    capability: str = "",
    error: Exception | None = None,
    tool_error: bool = False,
) -> None:
    result, code, message = (
        failure(error)
        if error
        else (("failed", "tool_error", "工具返回业务错误") if tool_error else ("success", "", ""))
    )
    db.add(
        McpActivity(
            tenant_id=actor.tenant.id,
            service_id=service.id,
            service_name=service.name,
            actor_id=actor.user.id,
            actor_name=actor.user.name,
            owner_id=owner(service, actor),
            category=category,
            operation=operation,
            capability=capability[:2000],
            source="access_key"
            if getattr(actor, "key", None)
            else "desktop"
            if getattr(actor, "device", None)
            else "console",
            access_key_id=getattr(getattr(actor, "key", None), "id", None),
            device_session_id=getattr(getattr(actor, "device", None), "id", None),
            client_version=getattr(getattr(actor, "device", None), "app_version", ""),
            result=result,
            error_code=code,
            message=message,
            duration_ms=int((time.monotonic() - started) * 1000),
            request_id=getattr(request.state, "request_id", uuid4().hex),
        )
    )
