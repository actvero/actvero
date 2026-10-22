"""Resource operations shared by Web and organization-scoped management routes.

Authentication and the final transaction commit belong to the caller.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Query, Request
from sqlalchemy import delete, func, or_, select

from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, provider
from app.modules.mcp import credentials
from app.modules.mcp import service as logic
from app.modules.mcp.importing import parse_import
from app.modules.mcp.models import (
    McpActivity,
    McpConnection,
    McpContent,
    McpHealth,
    McpOAuthAttempt,
    McpPolicy,
    McpService,
    McpSnapshot,
)
from app.modules.mcp.network import resolve
from app.modules.mcp.schemas import (
    McpActivityPage,
    McpActivityView,
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
    McpServiceInput,
    McpServicePage,
    McpServiceUpdate,
    McpServiceView,
    McpServiceWrite,
    normalize_icon,
)
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor, record


async def validate_config(
    request: Request,
    db: DB,
    actor: BusinessActor,
    body: McpServiceInput,
    service_id: UUID | None = None,
) -> None:
    logic.administrator(actor)
    duplicate = await db.scalar(
        select(McpService).where(
            McpService.tenant_id == actor.tenant.id, McpService.name == body.name
        )
    )
    if duplicate and duplicate.id != service_id:
        raise HTTPException(409, "已存在同名服务")
    if body.member_ids:
        members = (
            await db.scalars(
                select(Membership.id).where(
                    Membership.id.in_(body.member_ids),
                    Membership.tenant_id == actor.tenant.id,
                    Membership.status == "active",
                )
            )
        ).all()
        if set(members) != set(body.member_ids):
            raise HTTPException(422, "请选择当前组织的有效成员")
    if body.transport != "builtin":
        await resolve(body.url, provider(request).settings)
    if body.oauth:
        await resolve(body.oauth.authorization_url, provider(request).settings)
        await resolve(body.oauth.token_url, provider(request).settings)


async def services(actor: BusinessActor, request: Request, db: DB) -> McpServicePage:
    rows = (
        await db.scalars(
            select(McpService)
            .where(McpService.tenant_id == actor.tenant.id)
            .order_by(McpService.created_at)
        )
    ).all()
    return McpServicePage(
        items=[
            await logic.view(db, s, actor)
            for s in rows
            if actor.member.role == "administrator" or logic.visible(s, actor)
        ]
    )


async def create_service(
    actor: BusinessActor, request: Request, db: DB, body: McpServiceWrite
) -> McpServiceView:
    await validate_config(request, db, actor, body)
    body.icon = normalize_icon(body.icon)
    row = McpService(
        tenant_id=actor.tenant.id, **body.model_dump(mode="json", exclude={"credential_values"})
    )
    row.enabled = False
    db.add(row)
    await db.flush()
    if body.credential_values is not None:
        await credentials.store(request, db, row, actor, body.credential_values)
        await db.flush()
    record(db, actor, "mcp.create", row.id, row.name)
    result = await logic.view(db, row, actor)
    await db.flush()
    return result


async def update_service(
    actor: BusinessActor, service_id: UUID, request: Request, db: DB, body: McpServiceUpdate
) -> McpServiceView:
    row = await logic.get_service(db, actor, service_id, admin=True)
    if body.version != row.version:
        raise HTTPException(409, "配置已被修改，请刷新后重试")
    await validate_config(request, db, actor, body, row.id)
    if row.transport != "builtin" and body.transport == "builtin":
        raise HTTPException(422, "远程服务不能切换为内置内容")
    data = body.model_dump(mode="json", exclude={"version", "credential_values"})
    if data["icon"] != row.icon:
        data["icon"] = normalize_icon(data["icon"])
    changed = any(getattr(row, k) != data[k] for k in ("url", "transport", "auth_mode", "oauth"))
    changed = changed or [
        {k: v for (k, v) in f.items() if k != "label"} for f in row.credential_fields
    ] != [{k: v for (k, v) in f.items() if k != "label"} for f in data["credential_fields"]]
    if row.connection_options != data["connection_options"]:
        await db.execute(delete(McpHealth).where(McpHealth.service_id == row.id))
    for key, value in data.items():
        setattr(row, key, value)
    row.version += 1
    if changed:
        row.enabled = False
        row.catalog_initialized = False
        for cls in (McpConnection, McpSnapshot, McpOAuthAttempt, McpPolicy, McpHealth):
            await db.execute(delete(cls).where(cls.service_id == row.id))
    if body.credential_values is not None:
        await credentials.store(request, db, row, actor, body.credential_values)
        await db.flush()
    record(db, actor, "mcp.update", row.id, row.name)
    result = await logic.view(db, row, actor)
    await db.flush()
    return result


async def delete_service(
    actor: BusinessActor,
    service_id: UUID,
    request: Request,
    db: DB,
    expected_version: int | None = None,
) -> Message:
    row = await logic.get_service(db, actor, service_id, admin=True)
    if expected_version is not None and row.version != expected_version:
        raise HTTPException(409, "配置已被修改，请刷新后重试")
    record(db, actor, "mcp.delete", row.id, row.name)
    await db.delete(row)
    await db.flush()
    return Message(message="已删除服务及其连接")


async def presentation(
    actor: BusinessActor, service_id: UUID, request: Request, db: DB, body: McpPresentationUpdate
) -> McpServiceView:
    row = await logic.get_service(db, actor, service_id, admin=True)
    if row.version != body.version:
        raise HTTPException(409, "配置已被修改，请刷新后重试")
    if body.icon != row.icon:
        body.icon = normalize_icon(body.icon)
    for key, value in body.model_dump(exclude={"version"}).items():
        setattr(row, key, value)
    row.version += 1
    record(db, actor, "mcp.update", row.id, row.name)
    result = await logic.view(db, row, actor)
    await db.flush()
    return result


async def preview_import(
    actor: BusinessActor, request: Request, db: DB, body: McpImportRequest
) -> McpImportPreview:
    logic.administrator(actor)
    parsed = parse_import(body.configuration)
    for preview, item in parsed:
        if item:
            try:
                await validate_config(request, db, actor, item)
            except HTTPException as exc:
                preview.error = str(exc.detail)
    return McpImportPreview(
        items=[p for (p, _) in parsed], valid=all(not p.error for (p, _) in parsed)
    )


async def import_services(
    actor: BusinessActor, request: Request, db: DB, body: McpImportRequest | McpImport
) -> McpServicePage:
    logic.administrator(actor)
    config = (
        body.configuration if isinstance(body, McpImportRequest) else body.model_dump(mode="json")
    )
    parsed = parse_import(config)
    if any(p.error for (p, _) in parsed):
        raise HTTPException(422, "导入配置有误，请重新预览并修正")
    rows = []
    for _, item in parsed:
        assert item is not None
        await validate_config(request, db, actor, item)
        row = McpService(
            tenant_id=actor.tenant.id, **item.model_dump(mode="json", exclude={"credential_values"})
        )
        db.add(row)
        await db.flush()
        if item.credential_values is not None:
            await credentials.store(request, db, row, actor, item.credential_values)
        record(db, actor, "mcp.import", row.id, row.name)
        rows.append(row)
    await db.flush()
    result = McpServicePage(items=[await logic.view(db, s, actor) for s in rows])
    await db.flush()
    return result


async def export_services(actor: BusinessActor, request: Request, db: DB) -> McpImport:
    logic.administrator(actor)
    rows = (
        await db.scalars(
            select(McpService).where(
                McpService.tenant_id == actor.tenant.id, McpService.transport != "builtin"
            )
        )
    ).all()
    if not rows:
        raise HTTPException(409, "暂无可导出的远程服务")
    return McpImport(
        services=[
            McpServiceInput(
                **{
                    **(await logic.view(db, s, actor)).model_dump(
                        include=set(McpServiceInput.model_fields)
                    ),
                    "enabled": False,
                    "audience": "selected",
                    "member_ids": [],
                }
            )
            for s in rows
        ]
    )


async def capabilities(
    actor: BusinessActor, service_id: UUID, request: Request, db: DB
) -> McpCapabilities:
    return await logic.capability_view(db, await logic.get_service(db, actor, service_id), actor)


async def discover(
    actor: BusinessActor, service_id: UUID, request: Request, db: DB
) -> McpCapabilities:
    row = await logic.get_service(db, actor, service_id)
    result = await logic.refresh(request, db, row, actor)
    await db.flush()
    return result


async def policy(
    actor: BusinessActor, service_id: UUID, request: Request, db: DB, body: McpPolicyInput
) -> Message:
    row = await logic.get_service(db, actor, service_id, admin=True)
    snapshot = await db.get(McpSnapshot, (row.id, credentials.owner(row, actor)))
    if not snapshot or not any(
        c["kind"] == body.kind and c["key"] == body.key for c in snapshot.capabilities
    ):
        raise HTTPException(404, "请先发现当前账号下的能力")
    rule = await db.get(McpPolicy, (row.id, body.kind, body.key))
    if rule is None:
        rule = McpPolicy(service_id=row.id, kind=body.kind, key=body.key)
        db.add(rule)
    rule.definition_hash = logic.definition_hash(
        next(
            c["definition"]
            for c in snapshot.capabilities
            if c["kind"] == body.kind and c["key"] == body.key
        )
    )
    rule.enabled = body.enabled
    rule.description = body.description
    if row.transport == "builtin":
        for item in await logic.contents(db, row):
            if (
                item.name if item.kind == "prompts" else f"actvero://resources/{item.id}"
            ) == body.key and item.kind == body.kind:
                item.enabled = body.enabled
    record(db, actor, "mcp.policy", row.id, row.name)
    await db.flush()
    return Message(message="已更新能力")


async def set_connection(
    actor: BusinessActor, service_id: UUID, request: Request, db: DB, body: McpCredentials
) -> Message:
    row = await logic.get_service(db, actor, service_id)
    if row.auth_mode not in {"personal", "organization"}:
        raise HTTPException(422, "此服务不使用手工凭据")
    if row.auth_mode == "organization":
        logic.administrator(actor)
    if set(body.values) != {f["key"] for f in row.credential_fields} or any(
        not v or len(v) > 8192 or any(ord(c) < 32 or ord(c) > 126 for c in v)
        for v in body.values.values()
    ):
        raise HTTPException(422, "请完整填写所有凭据，且不能包含控制字符或非 ASCII 字符")
    await credentials.store(request, db, row, actor, body.values)
    record(db, actor, "mcp.connection", row.id, row.name)
    await db.flush()
    return Message(message="已保存，尚未验证；请测试连接")


async def disconnect(actor: BusinessActor, service_id: UUID, request: Request, db: DB) -> Message:
    row = await logic.get_service(db, actor, service_id)
    if row.auth_mode == "organization":
        logic.administrator(actor)
    from app.modules.desktop_mcp.oauth import cancel_pending

    await db.scalar(select(McpService).where(McpService.id == row.id).with_for_update())
    await cancel_pending(db, row.id, actor.member.id)
    for cls in (McpConnection, McpSnapshot, McpHealth):
        await db.execute(
            delete(cls).where(
                cls.service_id == row.id, cls.owner_id == credentials.owner(row, actor)
            )
        )
    await db.execute(
        delete(McpOAuthAttempt).where(
            McpOAuthAttempt.service_id == row.id, McpOAuthAttempt.member_id == actor.member.id
        )
    )
    record(db, actor, "mcp.disconnect", row.id, row.name)
    await db.flush()
    return Message(message="已断开平台连接")


async def run(
    actor: BusinessActor, service_id: UUID, request: Request, db: DB, body: McpRun
) -> McpResult:
    row = await logic.get_service(db, actor, service_id)
    result = await logic.run(request, db, row, actor, body)
    await db.flush()
    return result


async def list_contents(actor: BusinessActor, request: Request, db: DB) -> McpContents:
    logic.administrator(actor)
    rows = (
        await db.scalars(
            select(McpContent)
            .join(McpService)
            .where(McpService.tenant_id == actor.tenant.id)
            .order_by(McpContent.name)
        )
    ).all()
    return McpContents(
        items=[
            McpContentView(id=r.id, **{k: getattr(r, k) for k in McpContentInput.model_fields})
            for r in rows
        ]
    )


async def save_content(
    request: Request,
    db: DB,
    actor: BusinessActor,
    body: McpContentInput,
    content_id: UUID | None = None,
) -> McpContentView:
    row = await logic.get_service(db, actor, body.service_id, admin=True)
    if row.transport != "builtin":
        raise HTTPException(422, "请选择内置内容服务")
    item = await db.get(McpContent, content_id) if content_id else None
    if content_id and (not item or item.service_id != row.id or item.kind != body.kind):
        raise HTTPException(404, "内容不存在或类型不符")
    duplicate = await db.scalar(
        select(McpContent).where(
            McpContent.service_id == row.id,
            McpContent.kind == body.kind,
            McpContent.name == body.name,
        )
    )
    if duplicate and duplicate.id != content_id:
        raise HTTPException(409, "内容名称重复")
    if item:
        old_key = item.name if item.kind == "prompts" else f"actvero://resources/{item.id}"
        old_policy = await db.get(McpPolicy, (row.id, item.kind, old_key))
        if old_policy:
            await db.delete(old_policy)
    else:
        item = McpContent()
        db.add(item)
    for key, value in body.model_dump().items():
        setattr(item, key, value)
    await db.flush()
    record(db, actor, "mcp.content", row.id, row.name)
    await logic.refresh(request, db, row, actor)
    return McpContentView(id=item.id, **body.model_dump())


async def create_content(
    actor: BusinessActor, request: Request, db: DB, body: McpContentInput
) -> McpContentView:
    result = await save_content(request, db, actor, body)
    await db.flush()
    return result


async def update_content(
    actor: BusinessActor, content_id: UUID, request: Request, db: DB, body: McpContentInput
) -> McpContentView:
    result = await save_content(request, db, actor, body, content_id)
    await db.flush()
    return result


async def delete_content(
    actor: BusinessActor, content_id: UUID, request: Request, db: DB
) -> Message:
    item = await db.get(McpContent, content_id)
    if not item:
        raise HTTPException(404, "内容不存在")
    row = await logic.get_service(db, actor, item.service_id, admin=True)
    key = item.name if item.kind == "prompts" else f"actvero://resources/{item.id}"
    await db.execute(
        delete(McpPolicy).where(
            McpPolicy.service_id == row.id, McpPolicy.kind == item.kind, McpPolicy.key == key
        )
    )
    await db.delete(item)
    await db.flush()
    await logic.refresh(request, db, row, actor)
    record(db, actor, "mcp.content_delete", row.id, row.name)
    await db.flush()
    return Message(message="已删除内容")


async def activities(
    actor: BusinessActor,
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
    logic.administrator(actor)
    if since and since.tzinfo is None or (until and until.tzinfo is None):
        raise HTTPException(422, "时间须包含时区")
    if since and until and (since > until):
        raise HTTPException(422, "起始时间不能晚于结束时间")
    conditions = [McpActivity.tenant_id == actor.tenant.id, McpActivity.category == category]
    if service_id:
        conditions.append(McpActivity.service_id == service_id)
    if result:
        conditions.append(McpActivity.result == result)
    if since:
        conditions.append(McpActivity.created_at >= since)
    if until:
        conditions.append(McpActivity.created_at <= until)
    if q:
        conditions.append(
            or_(
                McpActivity.service_name.icontains(q, autoescape=True),
                McpActivity.actor_name.icontains(q, autoescape=True),
                McpActivity.capability.icontains(q, autoescape=True),
                McpActivity.request_id.icontains(q, autoescape=True),
            )
        )
    total = await db.scalar(select(func.count()).select_from(McpActivity).where(*conditions))
    rows = (
        await db.scalars(
            select(McpActivity)
            .where(*conditions)
            .order_by(McpActivity.created_at.desc(), McpActivity.id.desc())
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    return McpActivityPage(
        items=[McpActivityView.model_validate(row) for row in rows], total=total or 0, page=page
    )
