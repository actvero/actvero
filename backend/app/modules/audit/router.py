from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from app.modules.audit.models import AuditEvent
from app.modules.audit.schemas import EventPage, EventView
from app.modules.auth.service import DB
from app.modules.members.service import access

router = APIRouter(prefix="/api/v1/enterprises/{tenant_id}/events", tags=["audit"])


@router.get("", response_model=EventPage)
async def events(
    tenant_id: UUID,
    request: Request,
    db: DB,
    q: str = Query(default="", max_length=200),
    target_id: UUID | None = None,
    action: str | None = None,
    page: int = Query(default=1, ge=1),
    result: str = "",
    from_time: datetime | None = None,
    to_time: datetime | None = None,
) -> EventPage:
    await access(request, db, tenant_id)
    filters = [AuditEvent.tenant_id == tenant_id]
    for value in (from_time, to_time):
        if value and value.tzinfo is None:
            raise HTTPException(422, "时间筛选必须包含时区")
    if from_time and to_time and from_time > to_time:
        raise HTTPException(422, "开始时间不能晚于结束时间")
    if from_time:
        filters.append(AuditEvent.created_at >= from_time)
    if to_time:
        filters.append(AuditEvent.created_at <= to_time)
    if result:
        filters.append(AuditEvent.result == result)
    if target_id:
        filters.append(AuditEvent.target_id == target_id)
    if action:
        filters.append(AuditEvent.action == action)
    if q.strip():
        needle = "%" + q.strip().replace("%", "\\%").replace("_", "\\_") + "%"
        filters.append(
            or_(AuditEvent.actor_name.ilike(needle), AuditEvent.target_name.ilike(needle))
        )
    total = await db.scalar(select(func.count()).select_from(AuditEvent).where(*filters)) or 0
    rows = (
        await db.scalars(
            select(AuditEvent)
            .where(*filters)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .offset((page - 1) * 20)
            .limit(20)
        )
    ).all()
    return EventPage(items=[EventView.model_validate(row) for row in rows], total=total, page=page)


@router.get("/{event_id}", response_model=EventView)
async def detail(tenant_id: UUID, event_id: UUID, request: Request, db: DB) -> EventView:
    await access(request, db, tenant_id)
    row = await db.scalar(
        select(AuditEvent).where(AuditEvent.tenant_id == tenant_id, AuditEvent.id == event_id)
    )
    if row is None:
        raise HTTPException(404, "操作记录不存在")
    return EventView.model_validate(row)
