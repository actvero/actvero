import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, digest, now, provider
from app.modules.mcp import credentials, operations
from app.modules.mcp import service as logic
from app.modules.mcp.models import (
    McpOAuthAttempt,
    McpService,
)
from app.modules.mcp.network import resolve
from app.modules.mcp.schemas import (
    McpActivityPage,
    McpCapabilities,
    McpContentInput,
    McpContents,
    McpContentView,
    McpCredentials,
    McpImport,
    McpImportPreview,
    McpImportRequest,
    McpPolicyInput,
    McpPresentationUpdate,
    McpResult,
    McpRun,
    McpServicePage,
    McpServiceUpdate,
    McpServiceView,
    McpServiceWrite,
)
from app.modules.members.service import record

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


@router.get(
    "/services",
    summary="列出当前可见 MCP 服务",
    description="Web 登录。管理员可查看全部配置；普通成员仅返回总开关已开启且"
    "授权范围允许的服务。当前不是 DSH 目录接口。",
    response_model=McpServicePage,
)
async def services(request: Request, db: DB) -> McpServicePage:
    actor = await own_access(request, db)
    result = await operations.services(actor=actor, request=request, db=db)
    await db.commit()
    return result


@router.post(
    "/services",
    summary="添加 MCP 服务",
    description="仅管理员。新服务总开关强制关闭；保存配置不等于完成上游能力发现。",
    response_model=McpServiceView,
)
async def create_service(
    request: Request, db: DB, body: McpServiceWrite, _csrf: Mutation
) -> McpServiceView:
    actor = await own_access(request, db, write=True)
    result = await operations.create_service(actor=actor, request=request, db=db, body=body)
    await db.commit()
    return result


@router.put(
    "/services/{service_id}",
    summary="更新 MCP 服务配置",
    description="仅管理员。携带当前 version；并发修改返回冲突。使用范围与"
    "认证方式独立，秘密不会在读取接口回显。",
    response_model=McpServiceView,
)
async def update_service(
    service_id: UUID, request: Request, db: DB, body: McpServiceUpdate, _csrf: Mutation
) -> McpServiceView:
    actor = await own_access(request, db, write=True)
    result = await operations.update_service(
        actor=actor, service_id=service_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.delete(
    "/services/{service_id}",
    summary="删除 MCP 服务",
    description="仅管理员。删除服务配置及相关本地连接/目录数据，不等同于撤销第三方账号授权。",
    response_model=Message,
)
async def delete_service(service_id: UUID, request: Request, db: DB, _csrf: Mutation) -> Message:
    actor = await own_access(request, db, write=True)
    result = await operations.delete_service(
        actor=actor, service_id=service_id, request=request, db=db
    )
    await db.commit()
    return result


@router.put(
    "/services/{service_id}/presentation",
    summary="更新连接器展示资料",
    description="仅管理员。更新图标、展示名称、简介和使用示例，保留连接配置与成员范围。",
    response_model=McpServiceView,
)
async def presentation(
    service_id: UUID, request: Request, db: DB, body: McpPresentationUpdate, _csrf: Mutation
) -> McpServiceView:
    actor = await own_access(request, db, write=True)
    result = await operations.presentation(
        actor=actor, service_id=service_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.post(
    "/import/preview",
    summary="预览 MCP 导入配置",
    description="仅管理员。解析并检查配置，返回脱敏预览和问题；不创建服务。",
    response_model=McpImportPreview,
)
async def preview_import(
    request: Request, db: DB, body: McpImportRequest, _csrf: Mutation
) -> McpImportPreview:
    actor = await own_access(request, db)
    result = await operations.preview_import(actor=actor, request=request, db=db, body=body)
    await db.commit()
    return result


@router.post(
    "/import",
    summary="导入 MCP 服务",
    description="仅管理员。按导入内容重新校验并保存，新服务默认关闭；前端另外启动能力发现。",
    response_model=McpServicePage,
)
async def import_services(
    request: Request, db: DB, body: McpImportRequest | McpImport, _csrf: Mutation
) -> McpServicePage:
    actor = await own_access(request, db, write=True)
    result = await operations.import_services(actor=actor, request=request, db=db, body=body)
    await db.commit()
    return result


@router.get(
    "/export",
    summary="导出脱敏 MCP 配置",
    description="仅管理员。返回可导入的配置，排除秘密；目标实例需要重新配置业务凭据与使用范围。",
    response_model=McpImport,
)
async def export_services(request: Request, db: DB) -> McpImport:
    actor = await own_access(request, db)
    result = await operations.export_services(actor=actor, request=request, db=db)
    await db.commit()
    return result


@router.get(
    "/services/{service_id}/capabilities",
    summary="读取当前连接的能力目录",
    description="返回工具、提示词、资源和资源模板的已有目录；按调用者连接隔离。管"
    "理员测试目录与普通成员可使用目录不同。",
    response_model=McpCapabilities,
)
async def capabilities(service_id: UUID, request: Request, db: DB) -> McpCapabilities:
    actor = await own_access(request, db)
    result = await operations.capabilities(
        actor=actor, service_id=service_id, request=request, db=db
    )
    await db.commit()
    return result


@router.post(
    "/services/{service_id}/discover",
    summary="连接上游并刷新能力目录",
    description="按当前调用者本人或组织连接读取上游目录。首次成功的管理员发现开启"
    "返回子项，后续刷新保留选择；总开关不会因此自动开启。",
    response_model=McpCapabilities,
)
async def discover(service_id: UUID, request: Request, db: DB, _csrf: Mutation) -> McpCapabilities:
    actor = await own_access(request, db, write=True)
    result = await operations.discover(actor=actor, service_id=service_id, request=request, db=db)
    await db.commit()
    return result


@router.put(
    "/services/{service_id}/policy",
    summary="更新能力开关或说明",
    description="仅管理员。设置单个工具/提示词/资源/模板策略；开启能力仍受服务"
    "总开关和使用范围约束。",
    response_model=Message,
)
async def policy(
    service_id: UUID, request: Request, db: DB, body: McpPolicyInput, _csrf: Mutation
) -> Message:
    actor = await own_access(request, db, write=True)
    result = await operations.policy(
        actor=actor, service_id=service_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.put(
    "/services/{service_id}/connection",
    summary="保存业务凭据",
    description="personal 保存调用者本人凭据；organization "
    "仅管理员可更新组织共用凭据。只写不回显，保存后尚未验证，需要测试"
    "连接。",
    response_model=Message,
)
async def set_connection(
    service_id: UUID, request: Request, db: DB, body: McpCredentials, _csrf: Mutation
) -> Message:
    actor = await own_access(request, db, write=True)
    result = await operations.set_connection(
        actor=actor, service_id=service_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.delete(
    "/services/{service_id}/connection",
    summary="断开平台业务连接",
    description="personal/oauth 仅断开调用者本人连接；组织连接仅管"
    "理员可操作。清理本地连接及目录状态，不保证第三方令牌同步撤销。",
    response_model=Message,
)
async def disconnect(service_id: UUID, request: Request, db: DB, _csrf: Mutation) -> Message:
    actor = await own_access(request, db, write=True)
    result = await operations.disconnect(actor=actor, service_id=service_id, request=request, db=db)
    await db.commit()
    return result


@router.post(
    "/services/{service_id}/run",
    summary="测试 MCP 能力",
    description="Web 控制台测试入口，非标准 MCP JSON-RPC 网关。"
    "工具执行、提示词预览或资源读取按 kind 分支；验证成员范围、"
    "能力策略及连接身份。管理员可以测试尚未开放的能力，但不能借用其他"
    "成员凭据。工具可能有业务副作用，超时不得自动重跑。",
    response_model=McpResult,
)
async def run(
    service_id: UUID, request: Request, db: DB, body: McpRun, _csrf: Mutation
) -> McpResult:
    actor = await own_access(request, db, write=True)
    result = await operations.run(
        actor=actor, service_id=service_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


class McpAuthorizationUrl(BaseModel):
    url: str


@router.post(
    "/services/{service_id}/oauth",
    summary="开始本人的 MCP OAuth 授权",
    description="返回浏览器授权地址，绑定当前成员和 Web 会话。回调必须使用原"
    " Web 会话；尚不能直接用于 DSH 原生授权。",
    response_model=McpAuthorizationUrl,
)
async def start_oauth(
    service_id: UUID, request: Request, db: DB, _csrf: Mutation
) -> McpAuthorizationUrl:
    actor = await own_access(request, db, write=True)
    row = await logic.get_service(db, actor, service_id)
    await db.scalar(
        select(McpService)
        .where(McpService.id == row.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.auth_mode != "oauth" or not row.oauth:
        raise HTTPException(422, "此服务未配置 OAuth")
    await resolve(row.oauth["authorization_url"], provider(request).settings)
    from app.modules.desktop_mcp.oauth import cancel_pending

    await cancel_pending(db, row.id, actor.member.id)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    await db.execute(
        delete(McpOAuthAttempt).where(
            McpOAuthAttempt.member_id == actor.member.id, McpOAuthAttempt.service_id == row.id
        )
    )
    db.add(
        McpOAuthAttempt(
            state_hash=digest(state),
            service_id=row.id,
            member_id=actor.member.id,
            session_id=actor.session.id,
            version=row.version,
            verifier=provider(request).seal({"verifier": verifier}),
            expires_at=now() + timedelta(minutes=10),
        )
    )
    await db.commit()
    return McpAuthorizationUrl(
        url=row.oauth["authorization_url"]
        + "?"
        + urlencode(
            {
                "response_type": "code",
                "client_id": row.oauth["client_id"],
                "redirect_uri": provider(request).settings.app_url + "/api/v1/mcp/oauth/callback",
                "scope": row.oauth["scopes"],
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )


@router.get("/oauth/callback", include_in_schema=False)
async def oauth_callback(
    request: Request, db: DB, state: str = "", code: str = "", error: str = ""
) -> RedirectResponse:
    actor = await own_access(request, db, write=True)
    initial = await db.get(McpOAuthAttempt, digest(state))
    if initial:
        await db.scalar(
            select(McpService).where(McpService.id == initial.service_id).with_for_update()
        )
    attempt = await db.scalar(
        select(McpOAuthAttempt)
        .where(McpOAuthAttempt.state_hash == digest(state))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not attempt
        or attempt.expires_at <= now()
        or attempt.member_id != actor.member.id
        or attempt.session_id != actor.session.id
    ):
        raise HTTPException(400, "授权已失效，请从服务页面重新连接")
    row = await logic.get_service(db, actor, attempt.service_id)
    await db.delete(attempt)
    if error or not code or len(code) > 8192 or not row.oauth or row.version != attempt.version:
        await db.commit()
        return RedirectResponse("/mcp?oauth=failed", status_code=303)
    try:
        result = await credentials.token_request(
            request,
            row.oauth["token_url"],
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": row.oauth["client_id"],
                "redirect_uri": provider(request).settings.app_url + "/api/v1/mcp/oauth/callback",
                "code_verifier": provider(request).unseal(attempt.verifier)["verifier"],
            },
        )
    except Exception:
        record(db, actor, "mcp.oauth", row.id, row.name, result="failed")
        await db.commit()
        return RedirectResponse("/mcp?oauth=failed", status_code=303)
    await credentials.store(request, db, row, actor, result)
    record(db, actor, "mcp.oauth", row.id, row.name)
    await db.commit()
    actor = await own_access(request, db, write=True)
    row = await logic.get_service(db, actor, row.id)
    try:
        await logic.refresh(request, db, row, actor)
        await db.commit()
    except HTTPException:
        return RedirectResponse("/mcp?oauth=discovery_failed", status_code=303)
    return RedirectResponse("/mcp?oauth=connected", status_code=303)


@router.get(
    "/contents",
    summary="读取保留的内置内容",
    description="仅管理员。既有内置提示词/资源的兼容接口，当前页面不提供独立编写入口。",
    response_model=McpContents,
)
async def list_contents(request: Request, db: DB) -> McpContents:
    actor = await own_access(request, db)
    result = await operations.list_contents(actor=actor, request=request, db=db)
    await db.commit()
    return result


@router.post(
    "/contents",
    summary="创建内置内容（兼容接口）",
    description="仅管理员，仅适用于 builtin 服务。当前页面不提供独立编写入口。",
    response_model=McpContentView,
)
async def create_content(
    request: Request, db: DB, body: McpContentInput, _csrf: Mutation
) -> McpContentView:
    actor = await own_access(request, db, write=True)
    result = await operations.create_content(actor=actor, request=request, db=db, body=body)
    await db.commit()
    return result


@router.put(
    "/contents/{content_id}",
    summary="更新内置内容（兼容接口）",
    description="仅管理员，仅适用于原 builtin 服务，保留旧数据兼容。",
    response_model=McpContentView,
)
async def update_content(
    content_id: UUID, request: Request, db: DB, body: McpContentInput, _csrf: Mutation
) -> McpContentView:
    actor = await own_access(request, db, write=True)
    result = await operations.update_content(
        actor=actor, content_id=content_id, request=request, db=db, body=body
    )
    await db.commit()
    return result


@router.delete(
    "/contents/{content_id}",
    summary="删除内置内容（兼容接口）",
    description="仅管理员，删除对应内容及旧策略。",
    response_model=Message,
)
async def delete_content(content_id: UUID, request: Request, db: DB, _csrf: Mutation) -> Message:
    actor = await own_access(request, db, write=True)
    result = await operations.delete_content(
        actor=actor, content_id=content_id, request=request, db=db
    )
    await db.commit()
    return result


@router.get(
    "/activities",
    summary="查询 MCP 调用记录或连接日志",
    description="仅管理员。当前组织范围内筛选，服务器每页 20 条；只记录元数据"
    "，不返回参数、结果正文或凭据。",
    response_model=McpActivityPage,
)
async def activities(
    request: Request,
    db: DB,
    category: Literal["call", "connection"],
    page: int = Query(default=1, ge=1),
    service_id: UUID | None = None,
    result: Literal["success", "failed", "timeout"] | None = None,
    q: str = Query(default="", max_length=100),
    since: datetime | None = None,
    until: datetime | None = None,
) -> McpActivityPage:
    actor = await own_access(request, db)
    response = await operations.activities(
        actor=actor,
        request=request,
        db=db,
        category=category,
        page=page,
        service_id=service_id,
        result=result,
        q=q,
        since=since,
        until=until,
    )
    await db.commit()
    return response
