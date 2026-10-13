"""Administrator-only logical call list, detail and bounded usage summary."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request

from app.modules.auth.service import DB
from app.modules.llm.call_queries import (
    CallFilters,
    call_detail,
    call_page,
    usage_summary,
)
from app.modules.llm.call_schemas import CallDetail, CallPage, UsageSummary
from app.modules.llm.router import administrator

router = APIRouter(prefix="/api/v1/llm", tags=["llm-calls"])


@router.get("/calls", response_model=CallPage)
async def calls(
    request: Request,
    db: DB,
    from_time: Annotated[datetime | None, Query(alias="from")] = None,
    to_time: Annotated[datetime | None, Query(alias="to")] = None,
    timezone: Annotated[str, Query(min_length=1, max_length=100)] = "UTC",
    member_id: UUID | None = None,
    model_id: UUID | None = None,
    operation: Annotated[str | None, Query(max_length=30)] = None,
    source: Annotated[str, Query(max_length=20)] = "member",
    channel_id: UUID | None = None,
    unknown_channel: bool = False,
    result_status: Annotated[str | None, Query(max_length=30)] = None,
    settlement_status: Annotated[str | None, Query(max_length=100)] = None,
    call_id: UUID | None = None,
    held: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
) -> CallPage:
    actor = await administrator(request, db)
    return await call_page(
        db,
        CallFilters(
            tenant_id=actor.tenant.id,
            from_time=from_time,
            to_time=to_time,
            timezone_name=timezone,
            member_id=member_id,
            model_id=model_id,
            operation=operation,
            source=source,
            channel_id=channel_id,
            unknown_channel=unknown_channel,
            result_status=result_status,
            settlement_status=settlement_status,
            call_id=call_id,
            held=held,
        ),
        page,
    )


@router.get("/calls/{call_id}", response_model=CallDetail)
async def detail(call_id: UUID, request: Request, db: DB) -> CallDetail:
    actor = await administrator(request, db)
    return await call_detail(db, actor.tenant.id, call_id)


@router.get("/usage-summary", response_model=UsageSummary)
async def summary(
    request: Request,
    db: DB,
    from_time: Annotated[datetime, Query(alias="from")],
    to_time: Annotated[datetime, Query(alias="to")],
    timezone: Annotated[str, Query(min_length=1, max_length=100)] = "UTC",
    member_id: UUID | None = None,
    model_id: UUID | None = None,
    operation: Annotated[str | None, Query(max_length=30)] = None,
    source: Annotated[str, Query(max_length=20)] = "member",
    channel_id: UUID | None = None,
    unknown_channel: bool = False,
    result_status: Annotated[str | None, Query(max_length=30)] = None,
    settlement_status: Annotated[str | None, Query(max_length=100)] = None,
) -> UsageSummary:
    actor = await administrator(request, db)
    return await usage_summary(
        db,
        CallFilters(
            tenant_id=actor.tenant.id,
            from_time=from_time,
            to_time=to_time,
            timezone_name=timezone,
            member_id=member_id,
            model_id=model_id,
            operation=operation,
            source=source,
            channel_id=channel_id,
            unknown_channel=unknown_channel,
            result_status=result_status,
            settlement_status=settlement_status,
        ),
    )
