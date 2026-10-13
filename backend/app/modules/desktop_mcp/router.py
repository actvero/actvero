from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer
from sqlalchemy import delete, func, select

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, limit
from app.modules.desktop.errors import DesktopError, fail
from app.modules.desktop.router import BEARER
from app.modules.desktop.schemas import DesktopErrorResponse
from app.modules.desktop_mcp import oauth, service
from app.modules.desktop_mcp.schemas import (
    ConnectionState,
    Connector,
    ConnectorPage,
    OAuthAttemptView,
    PersonalCredentials,
    ResourceTokenInput,
    ResourceTokenView,
)
from app.modules.mcp import credentials
from app.modules.mcp import service as mcp
from app.modules.mcp.models import (
    McpConnection,
    McpHealth,
    McpOAuthAttempt,
    McpService,
    McpSnapshot,
)
from app.modules.mcp.schemas import CredentialField, validate_values
from app.modules.members.service import record

resource_bearer = HTTPBearer(
    scheme_name="McpResource",
    auto_error=False,
    description=(
        "由 /desktop/resource-tokens 获取。目录用 mcp:catalog；协议用 mcp:<服务ID>。"
        "只有 /api/mcp/services/<服务ID> 协议入口另接受个人访问密钥；"
        "/desktop/* 接口仍需桌面令牌。"
    ),
)
RESOURCE = [Depends(resource_bearer)]
RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": DesktopErrorResponse, "description": description}
    for status, description in {
        401: "令牌过期或设备失效；按 error.code 区分重新申请资源令牌与重新登录。",
        403: "资源范围不符、成员停用或组织不可用。",
        404: "连接器不可用，或授权尝试不属于本设备。",
        409: "认证模式不符或 OAuth 尚未完成；见 error.code。",
        422: "请求或凭据字段无效；不回显输入。",
        429: "请求过于频繁，遵守 Retry-After。",
        502: "上游连接验证失败，不返回原始异常或秘密。",
        503: "身份服务暂不可用；保留登录，稍后重试。",
        504: "上游超时，不自动重试业务工具。",
    }.items()
}
router = APIRouter(prefix="/api/v1/desktop", tags=["desktop-mcp"], responses=RESPONSES)


@router.post(
    "/resource-tokens",
    dependencies=BEARER,
    response_model=ResourceTokenView,
    summary="申请 MCP、LLM、Skills 或专家资源访问令牌",
    description="使用桌面登录 access_token。experts:catalog 用于专家目录与解析；"
    "skills:catalog 用于技能目录、预览与下载；"
    "MCP 目录申请 mcp:catalog，调用服务申请 mcp:<服务ID>；"
    "LLM 目录申请 llm:catalog，调用模型申请 llm:<模型UUID>。"
    "有效期最长 600 秒，到期重新申请。每次使用检查设备、成员及授权；"
    "不赋予管理员测试权限。",
)
async def resource_tokens(request: Request, db: DB, body: ResourceTokenInput) -> ResourceTokenView:
    if body.resource.startswith("llm:"):
        from app.modules.llm.runtime import issue

        return await issue(request, db, body.resource)
    # Authentication in issue occurs before any token is minted.
    return await service.issue(request, db, body.resource)


@router.get(
    "/mcp/connectors",
    dependencies=RESOURCE,
    response_model=ConnectorPage,
    summary="搜索并分页读取获准连接器",
    description="使用 mcp:catalog 资源令牌；仅返回已启用且授权给当前成员的服务，每页 20 条。"
    "q 搜索名称、展示名、简介；不返回上游地址、组织秘密、其他成员信息。没有可用服务返回空列表。",
)
async def connectors(
    request: Request, db: DB, page: int = Query(1, ge=1), q: str = Query("", max_length=100)
) -> ConnectorPage:
    actor = await service.authorize(request, db)
    conditions = list(service.visibility(actor))
    if q.strip():
        from sqlalchemy import or_

        conditions.append(
            or_(
                *[
                    field.icontains(q.strip(), autoescape=True)
                    for field in (McpService.name, McpService.display_name, McpService.description)
                ]
            )
        )
    total = await db.scalar(select(func.count()).select_from(McpService).where(*conditions))
    rows = (
        await db.scalars(
            select(McpService)
            .where(*conditions)
            .order_by(McpService.created_at, McpService.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    return ConnectorPage(
        items=[await service.connector(request, db, row, actor) for row in rows],
        total=total or 0,
        page=page,
    )


@router.get(
    "/mcp/connectors/{service_id}",
    dependencies=RESOURCE,
    response_model=Connector,
    summary="读取连接器详情与个人凭据表单",
    description=(
        "使用 mcp:catalog；返回展示信息、示例、协议地址及本人连接状态。撤权或服务关闭返回 404。"
    ),
)
async def detail(service_id: UUID, request: Request, db: DB) -> Connector:
    actor = await service.authorize(request, db)
    return await service.connector(
        request, db, await service.get_service(db, actor, service_id), actor
    )


@router.get(
    "/mcp/connectors/{service_id}/connection",
    dependencies=RESOURCE,
    response_model=ConnectionState,
    summary="查询本人连接状态",
    description=("只读已有状态，不访问上游。connected 表示最近发现成功，并非实时在线保证。"),
)
async def connection(service_id: UUID, request: Request, db: DB) -> ConnectionState:
    actor = await service.authorize(request, db)
    return await service.connection_state(
        request, db, await service.get_service(db, actor, service_id), actor
    )


@router.put(
    "/mcp/connectors/{service_id}/connection",
    dependencies=RESOURCE,
    response_model=ConnectionState,
    summary="保存本人的 MCP 凭据",
    description="仅 personal，全部字段必填、只写。替换本账号跨设备连接，返回 unverified。"
    "随后调用 /connection/verify。组织凭据只能在后台维护。",
)
async def save_connection(
    service_id: UUID, request: Request, db: DB, body: PersonalCredentials
) -> ConnectionState:
    actor = await service.authorize(request, db)
    row = await oauth.lock_service(db, actor, service_id)
    if row.auth_mode != "personal":
        fail(409, "personal_credentials_not_supported", "此连接器不接受个人手工凭据")
    values = {k: v.get_secret_value() for k, v in body.values.items()}
    try:
        validate_values([CredentialField.model_validate(f) for f in row.credential_fields], values)
    except ValueError:
        fail(422, "invalid_credentials", "请按字段定义完整填写凭据")
    await credentials.store(request, db, row, actor, values)
    record(db, actor, "mcp.connection", row.id, row.name)
    await db.commit()
    return ConnectionState(status="unverified", action="none")


@router.post(
    "/mcp/connectors/{service_id}/connection/verify",
    dependencies=RESOURCE,
    response_model=ConnectionState,
    summary="验证连接并发现当前身份的能力",
    description="连接上游读取目录，不执行工具。不会自动开启服务或能力；超时、失败返回稳定错误。可显式重试。",
)
async def verify_connection(service_id: UUID, request: Request, db: DB) -> ConnectionState:
    actor = await service.authorize(request, db)
    row = await service.get_service(db, actor, service_id)
    await limit(db, "native-mcp-verify:" + str(actor.device.id), 30, 60)
    original_version = row.version

    async def guard(_entry: dict[str, Any] | None) -> None:
        current_actor = await service.authorize(request, db)
        current = await service.get_service(db, current_actor, service_id)
        if current.version != original_version:
            raise HTTPException(409, "连接器配置已变化，请重新读取后重试")

    try:
        await mcp.refresh(request, db, row, actor, guard)
    except HTTPException as exc:
        error = DesktopError(
            exc.status_code,
            "authorization_unavailable"
            if exc.status_code == 503
            else "connection_verification_failed",
            "授权服务暂不可用，凭据已保留，请稍后重试"
            if exc.status_code == 503
            else "连接验证失败，请检查凭据或联系管理员",
        )
        error.headers = exc.headers
        raise error from None
    await db.commit()
    return await service.connection_state(request, db, row, actor)


@router.delete(
    "/mcp/connectors/{service_id}/connection",
    dependencies=RESOURCE,
    response_model=Message,
    summary="断开本人连接（影响本账号所有设备）",
    description="仅 personal/oauth。删除本人秘密及目录，取消未完成授权。"
    "不保证上游令牌撤销。"
    "只移除 DSH 本机连接器无需调用此接口。可重复调用。",
)
async def disconnect(service_id: UUID, request: Request, db: DB) -> Message:
    actor = await service.authorize(request, db)
    row = await oauth.lock_service(db, actor, service_id)
    if row.auth_mode not in {"personal", "oauth"}:
        fail(409, "personal_connection_not_supported", "此连接器没有可删除的个人连接")
    await oauth.cancel_pending(db, row.id, actor.member.id)
    await db.execute(
        delete(McpOAuthAttempt).where(
            McpOAuthAttempt.service_id == row.id, McpOAuthAttempt.member_id == actor.member.id
        )
    )
    for cls in (McpConnection, McpSnapshot, McpHealth):
        await db.execute(
            delete(cls).where(cls.service_id == row.id, cls.owner_id == actor.member.id)
        )
    record(db, actor, "mcp.disconnect", row.id, row.name)
    await db.commit()
    return Message(message="已断开本人连接")


@router.post(
    "/mcp/connectors/{service_id}/oauth-attempts",
    dependencies=RESOURCE,
    response_model=OAuthAttemptView,
    summary="发起本设备的个人 OAuth 授权",
    description="使用 mcp:catalog；返回浏览器地址，有效期 10 分钟。"
    "替换本人此服务未完成的尝试。"
    "浏览器回调只暂存结果；DSH 查询到 awaiting_confirmation 后必须调用 complete 才建立连接。",
)
async def start_oauth(service_id: UUID, request: Request, db: DB) -> OAuthAttemptView:
    actor = await service.authorize(request, db)
    await limit(db, "native-mcp-oauth:" + str(actor.device.id), 10, 300)
    return await oauth.start(request, db, actor, service_id)


@router.get(
    "/mcp/oauth-attempts/{attempt_id}",
    dependencies=RESOURCE,
    response_model=OAuthAttemptView,
    summary="查询本设备 OAuth 进度",
    description="建议每 2 秒查询，退出连接界面时停止。其他设备或成员返回 404，永不返回业务令牌。",
)
async def oauth_status(attempt_id: UUID, request: Request, db: DB) -> OAuthAttemptView:
    actor = await service.authorize(request, db)
    attempt = await oauth.own_attempt(db, actor, attempt_id)
    await service.get_service(db, actor, attempt.service_id)
    await db.commit()
    return oauth.view(attempt)


@router.delete(
    "/mcp/oauth-attempts/{attempt_id}",
    dependencies=RESOURCE,
    response_model=OAuthAttemptView,
    summary="取消本设备尚未完成的 OAuth",
    description="pending/exchanging/awaiting_confirmation 均可取消。迟到回调不会建立连接；"
    "completed 已建立的连接请用 connection DELETE 撤销。",
)
async def cancel_oauth(attempt_id: UUID, request: Request, db: DB) -> OAuthAttemptView:
    actor = await service.authorize(request, db)
    attempt = await oauth.own_attempt(db, actor, attempt_id)
    if attempt.status in oauth.ACTIVE:
        attempt.status = "cancelled"
        attempt.verifier = attempt.pending_tokens = None
    await db.commit()
    return oauth.view(attempt)


@router.post(
    "/mcp/oauth-attempts/{attempt_id}/complete",
    dependencies=RESOURCE,
    response_model=OAuthAttemptView,
    summary="确认并建立本设备发起的个人连接",
    description="仅原始成员和设备可确认。重新检查服务版本及授权；重复完成幂等。"
    "成功后调用 connection/verify。取消、过期、配置变化不会建立连接。",
)
async def complete_oauth(attempt_id: UUID, request: Request, db: DB) -> OAuthAttemptView:
    actor = await service.authorize(request, db)
    # Serialize with device revocation, and revalidate after acquiring its row lock.
    from app.modules.desktop.models import DeviceSession
    from app.modules.tenants.models import Tenant

    await db.scalar(select(Tenant).where(Tenant.id == actor.tenant.id).with_for_update())

    await db.scalar(
        select(DeviceSession).where(DeviceSession.id == actor.device.id).with_for_update()
    )
    actor = await service.authorize(request, db)
    return await oauth.complete(request, db, actor, attempt_id)


@router.get("/mcp/oauth/callback", include_in_schema=False)
async def oauth_callback(
    request: Request,
    db: DB,
    state: str = Query("", max_length=200),
    code: str = Query("", max_length=8192),
    error: str = Query("", max_length=200),
) -> HTMLResponse:
    await oauth.callback(request, db, state, code, error)
    return HTMLResponse(
        '<!doctype html><html lang="zh"><meta charset="utf-8"><title>Actvero 授权</title>'
        "<p>授权响应已处理。请返回桌面端查看结果并完成连接。</p></html>"
    )
