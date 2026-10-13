import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from html import escape
from uuid import uuid4

import httpx
import httpx2
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.requests import Request
from starlette.responses import Response

from app.api.router import router
from app.core.config import Settings
from app.core.database import Database
from app.core.errors import register_error_handlers
from app.modules.access_keys.router import router as access_keys_router
from app.modules.account.router import router as account_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.oidc import IdentityProvider
from app.modules.auth.router import router as auth_router
from app.modules.desktop.router import router as desktop_router
from app.modules.desktop.router import web_router as devices_router
from app.modules.desktop_mcp.gateway import router as mcp_gateway_router
from app.modules.desktop_mcp.router import router as desktop_mcp_router
from app.modules.desktop_skills.router import router as desktop_skills_router
from app.modules.experts.desktop import router as desktop_experts_router
from app.modules.experts.router import router as experts_router
from app.modules.llm import chat_router  # noqa: F401 -- registers chat handlers on shared routers
from app.modules.llm.call_router import router as llm_call_router
from app.modules.llm.catalog_router import router as llm_catalog_router
from app.modules.llm.dashboard_router import router as dashboard_router
from app.modules.llm.import_router import router as llm_import_router
from app.modules.llm.inference_router import admin_router as llm_test_router
from app.modules.llm.inference_router import router as llm_inference_router
from app.modules.llm.points import router as llm_points_router
from app.modules.llm.reference_catalog import router as llm_reference_router
from app.modules.llm.router import router as llm_router
from app.modules.llm.settlement_router import account_router as llm_account_router
from app.modules.llm.settlement_router import native_router as llm_member_router
from app.modules.llm.settlement_router import router as llm_settlement_router
from app.modules.llm.transcription_router import admin_router as transcription_test_router
from app.modules.llm.transcription_router import router as transcription_router
from app.modules.management.router import router as management_router
from app.modules.mcp.health import monitor, stop
from app.modules.mcp.router import router as mcp_router
from app.modules.members.invitations import router as invitations_router
from app.modules.members.router import router as members_router
from app.modules.platform.brand_limits import BrandUploadLimit
from app.modules.platform.brand_router import router as branding_router
from app.modules.platform.brand_sync import monitor_branding
from app.modules.platform.branding import public_branding
from app.modules.platform.downloads import router as client_downloads_router
from app.modules.platform.invitations import router as platform_invitations_router
from app.modules.platform.onboarding import router as onboarding_router
from app.modules.platform.router import router as platform_router
from app.modules.quota.router import router as quota_router
from app.modules.skills.limits import SkillUploadLimit
from app.modules.skills.router import router as skills_router
from app.modules.tenants.models import Installation
from app.modules.tenants.router import router as setup_router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database = Database(settings)
        application.state.database = database
        application.state.identity_provider = IdentityProvider(settings)
        from app.modules.llm.accounting_outbox import Outbox

        application.state.llm_outbox = Outbox(settings.llm_outbox_dir, database)
        application.state.llm_gateway = None
        accounting_task = asyncio.create_task(application.state.llm_outbox.run())
        health_task = asyncio.create_task(monitor(application)) if settings.database_url else None
        branding_task = (
            asyncio.create_task(monitor_branding(application)) if settings.database_url else None
        )
        try:
            yield
        finally:
            if branding_task is not None:
                branding_task.cancel()
                await asyncio.gather(branding_task, return_exceptions=True)
            accounting_task.cancel()
            await asyncio.gather(accounting_task, return_exceptions=True)
            if application.state.llm_gateway is not None:
                application.state.llm_gateway.close()
            await stop(health_task)
            await database.close()

    application = FastAPI(
        title="Actvero Platform API",
        version="0.1.0",
        description=(
            "Actvero 已实现接口。Web 管理 API 与桌面 API"
            " 使用不同认证方式。"
            "文档出现某个模块不代表已接通 DSH。"
            "桌面顺序：metadata → login/start → 系统"
            "浏览器登录 → login/exchange → me → bo"
            "otstrap。"
            "秘密字段示例仅为占位，不能当作真实凭据。"
        ),
        openapi_tags=[
            {
                "name": "desktop",
                "description": (
                    "DSH 主进程专用账号与设备接口。部分接口使用 DesktopA"
                    "ccess Bearer，"
                    "其余按请求体证明认证。所有桌面接口拒绝 Origin 或 Act"
                    "vero Web 登录 Cookie。"
                    "当前已登录的 Swagger 浏览器可能自动带 Cookie。"
                    "Try it out 失败时请用无 Cookie/Origin "
                    "的原生 HTTP 客户端，"
                    "不能关闭服务端校验。desktop:self 尚不能调用 MCP。"
                ),
            },
            {
                "name": "mcp",
                "description": (
                    "Web MCP 管理/测试 API 需要 Web 登录 Cookie；"
                    "写操作需要合法 Origin 和 X-CSRF-Token。"
                    "普通成员受服务启用、使用范围及能力开关约束，管理员可测试本人/组"
                    "织连接。"
                    "这里的 /run 是控制台测试接口，不是标准 MCP JSON-"
                    "RPC 网关，"
                    "不接受桌面 Bearer。"
                ),
            },
            {
                "name": "desktop-mcp",
                "description": (
                    "DSH 目录与本人连接。先用 DesktopAccess 申请资源令牌；其余"
                    "使用 McpResource。禁止 Web Cookie/Origin。"
                ),
            },
            {
                "name": "mcp-gateway",
                "description": (
                    "标准 MCP 协议入口；使用单服务资源令牌或指定服务范围的个人访问密钥。"
                ),
            },
            {
                "name": "access-keys",
                "description": (
                    "Web 本人密钥与管理员治理接口；写操作需要会话和 CSRF。"
                    "仅 /gateway/mcp/services 目录接受 PersonalAccessKey Bearer。"
                ),
            },
            {
                "name": "desktop-skills",
                "description": "DSH 技能目录、预览、下载与更新检查；使用 SkillsResource。",
            },
            {"name": "account", "description": "Web 本人资料与设备管理；使用 Web 登录会话。"},
        ],
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    application.add_middleware(SkillUploadLimit)
    application.add_middleware(BrandUploadLimit)
    register_error_handlers(application)
    application.include_router(router)
    for business_router in (
        auth_router,
        desktop_router,
        management_router,
        devices_router,
        account_router,
        access_keys_router,
        setup_router,
        members_router,
        invitations_router,
        audit_router,
        quota_router,
        platform_router,
        branding_router,
        client_downloads_router,
        onboarding_router,
        platform_invitations_router,
        mcp_router,
        llm_router,
        llm_inference_router,
        llm_test_router,
        transcription_router,
        transcription_test_router,
        llm_catalog_router,
        llm_import_router,
        llm_points_router,
        llm_settlement_router,
        llm_call_router,
        dashboard_router,
        llm_account_router,
        llm_member_router,
        llm_reference_router,
        skills_router,
        desktop_mcp_router,
        desktop_skills_router,
        experts_router,
        desktop_experts_router,
        mcp_gateway_router,
    ):
        application.include_router(business_router)

    @application.exception_handler(httpx2.HTTPError)
    @application.exception_handler(httpx.HTTPError)
    async def identity_unavailable(
        _request: Request, _error: httpx.HTTPError | httpx2.HTTPError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "identity_unavailable",
                    "message": "身份服务暂不可用，请稍后重试；本次操作未确认完成",
                    "request_id": getattr(_request.state, "request_id", ""),
                }
            },
        )

    @application.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path != "/api/docs":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "img-src 'self' data: blob:; font-src 'self' https://fonts.gstatic.com; "
                "connect-src 'self'; media-src 'self' blob:; "
                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            )
        return response

    static_root = settings.static_dir.resolve()

    @application.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str, request: Request) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="接口不存在")
        candidate = (static_root / path).resolve()
        if not candidate.is_relative_to(static_root):
            raise HTTPException(status_code=404, detail="文件不存在")
        if candidate.is_file() and candidate.name != "index.html":
            return FileResponse(candidate)
        if path.startswith(("assets/", "brand/")) or (candidate.suffix and path != "index.html"):
            raise HTTPException(status_code=404, detail="文件不存在")
        index = static_root / "index.html"
        if not index.is_file():
            raise HTTPException(
                status_code=404, detail=("前端尚未构建，请使用 make dev-web 或 make build")
            )
        brand = getattr(
            request.app.state, "brand_snapshot", public_branding(settings.app_url, None)
        )
        try:
            async with request.app.state.database.sessions() as db:
                async with asyncio.timeout(2):
                    brand = public_branding(settings.app_url, await db.get(Installation, 1))
            request.app.state.brand_snapshot = brand
        except Exception:
            # Presentation cache failure cannot make the sign-in page unavailable.
            pass
        html = index.read_text()
        html = html.replace("<title>Actvero</title>", "<title>" + escape(brand.name) + "</title>")
        html = html.replace(
            'href="/favicon.ico"', 'href="' + escape(brand.favicon_url, quote=True) + '"'
        )
        html = html.replace(
            'href="/brand/actvero-icon.png"',
            'href="' + escape(brand.apple_icon_url, quote=True) + '"',
        )
        html = html.replace(
            "Actvero · 统一 AI 能力管理平台",
            escape(brand.name, quote=True) + " · 统一 AI 能力管理平台",
        )
        snapshot = (
            json.dumps(brand.model_dump(mode="json"), ensure_ascii=True)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
        )
        html = html.replace(
            "</head>",
            '<script id="platform-branding" type="application/json">'
            + snapshot
            + "</script></head>",
        )
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    return application


app = create_app()
