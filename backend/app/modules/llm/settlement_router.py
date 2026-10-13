import hmac
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from app.modules.account.service import own_access
from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, provider
from app.modules.desktop import service as desktop
from app.modules.desktop.errors import fail
from app.modules.desktop_mcp.service import business_actor
from app.modules.llm import member_catalog, reconciliation, settlement
from app.modules.llm.call_queries import result_status, safe_code
from app.modules.llm.catalog_schemas import OperationKind, TokenPrice
from app.modules.llm.models import CatalogModel, ModelCall, MutationReceipt, UsageSettlement
from app.modules.llm.points import decimal_text
from app.modules.llm.reconciliation_schemas import (
    ReconcileInput,
    ReconciliationPreview,
    TaggedUsage,
)
from app.modules.llm.router import administrator
from app.modules.members.models import Membership
from app.modules.members.service import record
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/llm", tags=["llm-settlement"])
native_router = APIRouter(prefix="/api/v1/desktop/llm", tags=["desktop-llm"])
account_router = APIRouter(prefix="/api/v1/account/llm", tags=["account-llm"])


class WindowView(BaseModel):
    rule: dict[str, Any]
    used: str
    reserved: str
    remaining: str
    started_at: datetime | None
    resets_at: datetime | None


class QuotaView(BaseModel):
    status: Literal["active", "unconfigured"]
    policy: dict[str, Any] | None
    windows: list[WindowView]


class SettlementView(BaseModel):
    id: UUID
    member_id: UUID
    member_name: str
    model_name: str
    kind: str
    metric: Literal["tokens", "characters", "search_units", "images", "seconds"]
    status: str
    result_status: Literal["success", "failed", "interrupted", "cancelled", "unknown"]
    settlement_status: Literal["reserved", "review", "settled", "released"]
    terminal_reason: str | None
    version: int
    points: str | None
    reserved_points: str
    usage: dict[str, Any]
    created_at: datetime
    settled_at: datetime | None
    reason: str


class SettlementPage(BaseModel):
    items: list[SettlementView]
    total: int


class ReconciliationContext(BaseModel):
    settlement: SettlementView
    price: TokenPrice
    ratio: str
    currency: str
    required_fields: list[str]
    eligible: bool
    available_after: datetime | None


async def owned_settlement(db: DB, tenant_id: UUID, call_id: UUID) -> UsageSettlement:
    row = await db.get(UsageSettlement, call_id, populate_existing=True)
    if row is None or row.tenant_id != tenant_id:
        fail(404, "settlement_not_found", "结算记录不存在")
    return row


def assert_reconcilable(row: UsageSettlement, version: int) -> None:
    if row.version != version or row.status not in ("review", "reserved"):
        fail(409, "settlement_changed", "记录已处理，请刷新")
    if not reconciliation.eligible(row):
        fail(409, "request_in_progress", "请求尚在执行，暂不能核对")


def settlement_view(
    row: UsageSettlement, user: User, model: CatalogModel, call: ModelCall, *, public: bool = False
) -> SettlementView:
    return SettlementView(
        id=row.id,
        member_id=row.member_id,
        member_name=user.name,
        model_name=model.name,
        kind=call.kind,
        metric=row.price.get("metric", "tokens"),
        status=row.status,
        result_status=cast(Any, result_status(call)),
        settlement_status=cast(Any, row.status),
        terminal_reason=safe_code(call.termination_code),
        version=row.version,
        points=decimal_text(settlement.points(row.amount, row.ratio))
        if row.amount is not None
        else None,
        reserved_points=decimal_text(settlement.points(row.reserved_amount, row.ratio))
        if row.status in ("reserved", "review")
        else "0",
        usage=public_usage(row.usage) if public else row.usage,
        created_at=row.created_at,
        settled_at=row.settled_at,
        reason="" if public else row.reason,
    )


_PUBLIC_USAGE_FIELDS = {
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_5m_tokens",
    "cache_write_1h_tokens",
    "input_characters",
    "search_units",
    "image_count",
    "audio_duration_ms",
    "input",
    "output",
    "cache_read",
    "cache_write_5m",
    "cache_write_1h",
}


def public_usage(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    result = {
        field: value
        for field, value in raw.items()
        if field in _PUBLIC_USAGE_FIELDS and type(value) is int and 0 <= value <= 10**12
    }
    if raw.get("source") in {"upstream", "validated_input", "confirmed_delivery", "unknown"}:
        result["source"] = raw["source"]
    return result


async def history(
    db: DB,
    tenant_id: UUID,
    member_id: UUID | None,
    state: str,
    page: int,
    *,
    public: bool = False,
) -> SettlementPage:
    filters = [UsageSettlement.tenant_id == tenant_id]
    if member_id:
        filters.append(UsageSettlement.member_id == member_id)
    if state:
        filters.append(UsageSettlement.status == state)
    total = await db.scalar(select(func.count()).select_from(UsageSettlement).where(*filters))
    rows = await db.execute(
        select(UsageSettlement, User, CatalogModel, ModelCall)
        .join(Membership, Membership.id == UsageSettlement.member_id)
        .join(User, User.id == Membership.user_id)
        .join(ModelCall, ModelCall.id == UsageSettlement.id)
        .join(CatalogModel, CatalogModel.id == ModelCall.model_id)
        .where(*filters)
        .order_by(UsageSettlement.created_at.desc())
        .offset((page - 1) * 20)
        .limit(20)
    )
    return SettlementPage(
        total=total or 0,
        items=[settlement_view(e, u, m, call, public=public) for e, u, m, call in rows],
    )


@router.get("/settlements", response_model=SettlementPage)
async def entries(
    request: Request,
    db: DB,
    state: Literal["", "reserved", "review", "settled", "released"] = "",
    page: int = Query(1, ge=1),
    member_id: UUID | None = None,
) -> SettlementPage:
    actor = await administrator(request, db)
    return await history(db, actor.tenant.id, member_id, state, page)


@router.get("/settlements/{call_id}/reconciliation", response_model=ReconciliationContext)
async def reconciliation_context(call_id: UUID, request: Request, db: DB) -> ReconciliationContext:
    actor = await administrator(request, db)
    row = await owned_settlement(db, actor.tenant.id, call_id)
    details = await db.execute(
        select(User, CatalogModel, ModelCall)
        .join(Membership, Membership.user_id == User.id)
        .join(UsageSettlement, UsageSettlement.member_id == Membership.id)
        .join(ModelCall, ModelCall.id == UsageSettlement.id)
        .join(CatalogModel, CatalogModel.id == ModelCall.model_id)
        .where(UsageSettlement.id == call_id, UsageSettlement.tenant_id == actor.tenant.id)
    )
    linked = details.one_or_none()
    if linked is None:
        fail(404, "settlement_not_found", "结算记录不存在")
    user, model, call = linked
    price = TokenPrice.model_validate(row.price)
    return ReconciliationContext(
        settlement=settlement_view(row, user, model, call),
        price=price,
        ratio=decimal_text(row.ratio),
        currency=row.currency,
        required_fields=reconciliation.required_fields(price),
        eligible=reconciliation.eligible(row),
        available_after=reconciliation.available_after(row),
    )


@router.post("/settlements/{call_id}/reconcile/preview", response_model=ReconciliationPreview)
async def reconciliation_preview(
    call_id: UUID, body: ReconcileInput, request: Request, db: DB, _: Mutation
) -> ReconciliationPreview:
    actor = await administrator(request, db)
    row = await owned_settlement(db, actor.tenant.id, call_id)
    assert_reconcilable(row, body.version)
    price = TokenPrice.model_validate(row.price)
    usage = reconciliation.canonical_usage(price, body)
    return reconciliation.preview(row, body, usage)


@router.post("/settlements/{call_id}/reconcile", response_model=SettlementPage)
async def reconcile(
    call_id: UUID, body: ReconcileInput, request: Request, db: DB, _: Mutation
) -> SettlementPage:
    actor = await administrator(request, db, write=True)
    row = await owned_settlement(db, actor.tenant.id, call_id)
    if isinstance(body.usage, TaggedUsage) and body.request_id is None:
        fail(422, "request_id_required", "按计量类型核对须提供请求标识")
    price = TokenPrice.model_validate(row.price)
    usage = reconciliation.canonical_usage(price, body)
    signature = (
        reconciliation.receipt_digest(provider(request).settings, call_id, body, usage)
        if body.request_id
        else None
    )
    if body.request_id:
        previous = await db.scalar(
            select(MutationReceipt).where(
                MutationReceipt.tenant_id == actor.tenant.id,
                MutationReceipt.actor_id == actor.user.id,
                MutationReceipt.scope == "settlement.reconcile",
                MutationReceipt.request_id == body.request_id,
            )
        )
        if previous:
            if previous.resource_id != call_id or not hmac.compare_digest(
                previous.payload_digest, signature or ""
            ):
                fail(409, "request_id_conflict", "此请求标识已用于其他核对内容")
            if previous.state != "completed":
                fail(409, "request_in_progress", "核对请求仍在处理，请查询回执")
            return await history(db, actor.tenant.id, row.member_id, "", 1)
    assert_reconcilable(row, body.version)
    # The preview uses the immutable admission price and ratio, not current policy.
    reconciliation.preview(row, body, usage)
    applied = await settlement.complete(
        db,
        call_id,
        usage,
        delivered=body.action == "settle",
        certainly_unused=body.action == "release",
        manual=True,
        expected_version=body.version,
    )
    if not applied:
        fail(409, "settlement_changed", "记录已处理，请刷新")
    row.reason = body.reason.strip()
    record(
        db,
        actor,
        "llm.settlement.reconcile",
        call_id,
        "模型用量核对",
        {"action": body.action, "reason": row.reason},
    )
    if body.request_id:
        db.add(
            MutationReceipt(
                tenant_id=actor.tenant.id,
                actor_id=actor.user.id,
                scope="settlement.reconcile",
                request_id=body.request_id,
                payload_digest=signature,
                resource_id=call_id,
                state="completed",
            )
        )
    await db.commit()
    return await history(db, actor.tenant.id, row.member_id, "", 1)


@router.get("/members/{member_id}/quota", response_model=QuotaView)
async def member_quota(member_id: UUID, request: Request, db: DB) -> QuotaView:
    from app.modules.members.service import BusinessActor

    actor = await administrator(request, db)
    member = await db.get(Membership, member_id)
    if member is None or member.tenant_id != actor.tenant.id or member.status != "active":
        fail(404, "member_unavailable", "成员不存在或已停用")
    return QuotaView.model_validate(
        await settlement.snapshot(
            db, BusinessActor(user=actor.user, tenant=actor.tenant, member=member)
        )
    )


@native_router.get("/quota", response_model=QuotaView)
async def my_quota(request: Request, db: DB) -> QuotaView:
    actor = await business_actor(
        db,
        await desktop.desktop_actor(request, db),
        platform_edition=provider(request).settings.platform_edition,
    )
    return QuotaView.model_validate(await settlement.snapshot(db, actor))


@account_router.get("/quota", response_model=QuotaView)
async def account_quota(request: Request, db: DB) -> QuotaView:
    actor = await own_access(request, db)
    return QuotaView.model_validate(await settlement.snapshot(db, actor))


@account_router.get("/usage", response_model=SettlementPage)
async def account_usage(
    request: Request,
    db: DB,
    page: int = Query(1, ge=1),
    state: Literal["", "reserved", "review", "settled", "released"] = "",
) -> SettlementPage:
    actor = await own_access(request, db)
    return await history(db, actor.tenant.id, actor.member.id, state, page, public=True)


@account_router.get("/models", response_model=member_catalog.MemberModelPage)
async def account_models(
    request: Request,
    db: DB,
    q: str = Query("", max_length=80),
    operation: OperationKind | None = None,
    page: int = Query(1, ge=1),
) -> member_catalog.MemberModelPage:
    actor = await own_access(request, db)
    return await member_catalog.member_page(db, actor, q=q, operation=operation, page=page)


@native_router.get("/usage", response_model=SettlementPage)
async def my_usage(
    request: Request,
    db: DB,
    page: int = Query(1, ge=1),
    state: Literal["", "reserved", "review", "settled", "released"] = "",
) -> SettlementPage:
    actor = await business_actor(
        db,
        await desktop.desktop_actor(request, db),
        platform_edition=provider(request).settings.platform_edition,
    )
    return await history(db, actor.tenant.id, actor.member.id, state, page, public=True)
