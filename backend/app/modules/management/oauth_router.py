"""CLI-owned authorization, with a browser-only callback that stages credentials."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Request
from fastapi.responses import PlainTextResponse

from app.modules.auth.service import DB
from app.modules.desktop.errors import fail
from app.modules.management import oauth
from app.modules.management.resources import mutate_resource, read_resource
from app.modules.management.schemas import ManagementOAuthView, ResourceResult
from app.modules.management.settings import require_enabled

router = APIRouter(prefix="/api/v1/management", tags=["management-resources"])


@router.post("/organizations/{org_id}/mcp/services/{service_id}/oauth/start")
async def start(
    org_id: UUID,
    service_id: UUID,
    request: Request,
    db: DB,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
) -> ResourceResult[ManagementOAuthView]:
    return await mutate_resource(
        request, db, org_id, request_id, oauth.start, retain_result=False, service_id=service_id
    )


@router.get("/organizations/{org_id}/mcp/oauth/{attempt_id}")
async def status(
    org_id: UUID, attempt_id: UUID, request: Request, db: DB
) -> ResourceResult[ManagementOAuthView]:
    return await read_resource(request, db, org_id, oauth.status, attempt_id=attempt_id)


@router.post("/organizations/{org_id}/mcp/oauth/{attempt_id}/complete")
async def complete(
    org_id: UUID,
    attempt_id: UUID,
    request: Request,
    db: DB,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
) -> ResourceResult[ManagementOAuthView]:
    return await mutate_resource(
        request, db, org_id, request_id, oauth.complete, attempt_id=attempt_id
    )


@router.post("/organizations/{org_id}/mcp/oauth/{attempt_id}/cancel")
async def cancel(
    org_id: UUID,
    attempt_id: UUID,
    request: Request,
    db: DB,
    request_id: Annotated[UUID, Header(alias="X-Management-Request-ID")],
) -> ResourceResult[ManagementOAuthView]:
    return await mutate_resource(
        request, db, org_id, request_id, oauth.cancel, attempt_id=attempt_id
    )


@router.get("/mcp/oauth/callback", include_in_schema=False)
async def callback(request: Request, db: DB) -> PlainTextResponse:
    await require_enabled(request, db)
    values = request.query_params
    if (
        any(len(values.getlist(key)) > 1 for key in ("state", "code", "error"))
        or not 1 <= len(values.get("state", "")) <= 200
        or len(values.get("code", "")) > 4096
        or len(values.get("error", "")) > 200
    ):
        fail(400, "invalid_oauth_callback", "无效授权回调")
    await oauth.callback(
        request, db, values.get("state", ""), values.get("code", ""), values.get("error", "")
    )
    return PlainTextResponse(
        "浏览器授权已处理。请返回 CLI 查询状态，并使用 oauth complete 确认连接。",
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
