"""Read-only publication checks and member previews; never admit model requests."""

from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.modules.auth.service import DB
from app.modules.llm.catalog_schemas import (
    ChatPolicy,
    ModelCapabilities,
    OperationKind,
    ReasoningOption,
)
from app.modules.llm.models import CatalogModel
from app.modules.llm.points import current_conversion
from app.modules.llm.settlement import snapshot
from app.modules.members.models import Membership
from app.modules.members.service import BusinessActor
from app.modules.model_gateway import client, publication, service
from app.modules.users.models import User

ModelName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@+\-]{0,127}$")]


class PublicationNames(BaseModel):
    models: list[ModelName] = Field(min_length=1, max_length=1000)


class PublicationCheck(BaseModel):
    key: Literal["relay", "channels", "pricing", "conversion", "parameters", "members"]
    label: str
    status: Literal["ready", "blocked", "unknown"]
    message: str
    action: Literal["deployment", "channels", "pricing", "quota", "parameters", "members"]


class Checks(list[PublicationCheck]):
    def add(self, key: Any, label: str, ready: bool | None, message: str, action: Any) -> None:
        self.append(
            PublicationCheck(
                key=key,
                label=label,
                status="unknown" if ready is None else "ready" if ready else "blocked",
                message=message,
                action=action,
            )
        )


class PublicationStatus(BaseModel):
    model_name: str
    enabled: bool
    audience: Literal["administrators", "organization", "selected"]
    member_count: int
    ready: bool
    checks: list[PublicationCheck]
    active_channels: int
    latest_test_at: int | None = None
    automatic: dict[str, Any] = Field(default_factory=dict)
    kind: OperationKind
    context_window: int | None = None
    max_output: int | None = None
    capabilities: ModelCapabilities
    reasoning_options: list[ReasoningOption] = Field(default_factory=list)
    chat_policy: ChatPolicy


class PublicationStatuses(BaseModel):
    items: list[PublicationStatus]


class PublicationPreviewInput(BaseModel):
    draft: publication.PublicationInput
    member_id: UUID | None = None


class PublicationPreview(BaseModel):
    configuration: PublicationStatus
    member_name: str | None = None
    discoverable: bool | None = None
    access_message: str | None = None
    quota_status: Literal["active", "unconfigured", "exhausted"] | None = None
    remaining_points: str | None = None
    resets_at: str | None = None


async def inspect(
    request: Request,
    db: DB,
    actor: BusinessActor,
    names: list[str],
    draft: publication.PublicationInput | None = None,
) -> list[PublicationStatus]:
    connection = await client.relay_connection(request, actor.tenant.id)
    rows = {
        row.slug: row
        for row in await db.scalars(
            select(CatalogModel).where(
                CatalogModel.tenant_id == actor.tenant.id, CatalogModel.slug.in_(names)
            )
        )
    }
    channels: list[dict[str, Any]] | None
    try:
        channels = await service.all_channels(request, actor.tenant.id)
    except HTTPException:
        channels = None
    prices: dict[str, Any] = {}
    pricing_known = True
    try:
        for offset in range(0, len(names), 100):
            data = await client.call(
                request,
                actor.tenant.id,
                "GET",
                "/api/option/model_pricing",
                params={"model": names[offset : offset + 100]},
            )
            prices.update({item["model_name"]: item for item in data.get("entries", [])})
    except HTTPException:
        pricing_known = False
    conversion = await current_conversion(db, actor.tenant.id)
    results = []
    for name in names:
        row = rows.get(name)
        saved = publication.view(row)
        body = (
            draft
            if draft and draft.model_name == name
            else publication.PublicationInput(
                **(
                    {"name": name, "model_name": name}
                    | {
                        k: v
                        for k, v in saved.items()
                        if k in publication.PublicationInput.model_fields
                    }
                )
            )
        )
        checks = Checks()

        add = checks.add

        relay_ready = bool(connection.relay_key and connection.relay_token_id)
        add(
            "relay",
            "调用连接",
            relay_ready,
            "已配置" if relay_ready else "尚未配置网关调用凭据",
            "deployment",
        )
        routes = [
            c
            for c in channels or []
            if c.get("status") == 1
            and name in (c.get("models") or "").split(",")
            and connection.relay_group in (c.get("group") or "").split(",")
        ]
        add(
            "channels",
            "渠道映射",
            bool(routes) if channels is not None else None,
            f"{len(routes)} 个启用渠道"
            if routes
            else "未关联当前调用分组的启用渠道"
            if channels is not None
            else "暂时无法读取渠道状态",
            "channels",
        )
        effective = (prices.get(name) or {}).get("effective") or {}
        priced = any(
            k in effective for k in ("ModelRatio", "ModelPrice", "billing_setting.billing_expr")
        )
        add(
            "pricing",
            "模型价格",
            priced if pricing_known else None,
            "已配置" if priced else "尚未配置模型价格" if pricing_known else "暂时无法读取价格",
            "pricing",
        )
        converted = bool(conversion and conversion.currency == "USD")
        add(
            "conversion",
            "积分换算",
            converted,
            "已配置" if converted else "尚未配置美元与积分的换算",
            "quota",
        )
        resolved_body, automatic = publication.resolve_body(
            body, connection.relay_group, channels or []
        )
        try:
            publication.configuration(
                actor.tenant.id,
                connection.base_url,
                resolved_body.model_copy(
                    update={"enabled": True, "audience": "administrators", "member_ids": []}
                ),
                automatic,
            )
            parameter_error = None
        except (ValueError, ValidationError):
            parameter_error = "必要模型参数缺失或不匹配，暂不能开放"
        if (
            body.kind == "chat"
            and body.capability_mode == "auto"
            and automatic.get("status") != "resolved"
        ):
            parameter_error = automatic.get("reason", "模型参数尚未识别")
        # The relay cannot reserve transcription duration with reliable native evidence yet.
        if body.kind == "transcription":
            parameter_error = "此用途暂不支持可靠的网关费用预留"
        add(
            "parameters",
            "模型参数",
            not parameter_error,
            parameter_error or "参数已就绪",
            "parameters",
        )
        if body.audience == "selected":
            active = set(
                await db.scalars(
                    select(Membership.id).where(
                        Membership.tenant_id == actor.tenant.id,
                        Membership.status == "active",
                        Membership.id.in_(body.member_ids),
                    )
                )
            )
            members_ready = bool(active) and active == set(body.member_ids)
            add(
                "members",
                "指定成员",
                members_ready,
                "所选成员有效" if members_ready else "请选择本组织的有效成员",
                "members",
            )
        results.append(
            PublicationStatus(
                model_name=name,
                enabled=body.enabled,
                audience=body.audience,
                member_count=len(set(body.member_ids)),
                ready=all(c.status == "ready" for c in checks),
                checks=checks,
                active_channels=len(routes),
                latest_test_at=max((int(c.get("test_time") or 0) for c in routes), default=0)
                or None,
                automatic=automatic,
                kind=resolved_body.kind,
                context_window=resolved_body.context_window,
                max_output=resolved_body.max_output,
                capabilities=resolved_body.capabilities,
                reasoning_options=resolved_body.reasoning_options,
                chat_policy=resolved_body.chat_policy,
            )
        )
    return results


async def preview(
    request: Request, db: DB, actor: BusinessActor, body: PublicationPreviewInput
) -> PublicationPreview:
    # Check target membership before querying control-plane state. No foreign member data leaks.
    member = None
    if body.member_id:
        member = await db.scalar(
            select(Membership).where(
                Membership.id == body.member_id,
                Membership.tenant_id == actor.tenant.id,
            )
        )
        if member is None:
            raise HTTPException(404, "成员不存在")
    status = (await inspect(request, db, actor, [body.draft.model_name], body.draft))[0]
    result = PublicationPreview(configuration=status)
    if member is None:
        return result
    user = await db.get(User, member.user_id)
    assert user is not None
    result.member_name = user.name
    allowed = body.draft.enabled and (
        body.draft.audience == "organization"
        or body.draft.audience == "administrators"
        and member.role == "administrator"
        or body.draft.audience == "selected"
        and member.id in body.draft.member_ids
    )
    result.discoverable = member.status == "active" and allowed and status.ready
    result.access_message = (
        "成员当前已暂停"
        if member.status != "active"
        else "此模型尚未开放"
        if not body.draft.enabled
        else "该成员不在使用范围内"
        if not allowed
        else "接入检查未通过，成员暂不能使用"
        if not status.ready
        else "该成员可在桌面模型目录中发现此模型"
    )
    state = await snapshot(db, BusinessActor(user, member, actor.tenant))
    result.quota_status = "active" if state["status"] == "active" else "unconfigured"
    if state["windows"]:
        limiting = min(state["windows"], key=lambda w: Decimal(w["remaining"]))
        result.remaining_points = limiting["remaining"]
        result.resets_at = limiting["resets_at"]
        if Decimal(limiting["remaining"]) <= 0:
            result.quota_status = "exhausted"
            exhausted = [w for w in state["windows"] if Decimal(w["remaining"]) <= 0]
            result.resets_at = (
                max(w["resets_at"] for w in exhausted)
                if all(w["resets_at"] for w in exhausted)
                else None
            )
    return result
