"""Explicit adoption receipts reuse native scopes and immutable published proofs."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now
from app.modules.desktop.errors import fail
from app.modules.desktop.models import ResourceAdoption
from app.modules.desktop.resources import NativeActor


class AdoptionView(BaseModel):
    id: UUID
    request_id: UUID
    resource_id: UUID
    version_id: UUID
    sha256: str
    kind: Literal["skills", "experts"]
    created_at: datetime


def view(row: ResourceAdoption) -> AdoptionView:
    return AdoptionView.model_validate(row, from_attributes=True)


async def proof(
    db: AsyncSession,
    actor: NativeActor,
    kind: str,
    resource_id: UUID,
    version_id: UUID,
    sha256: str,
) -> bool:
    return bool(
        await db.scalar(
            select(ResourceAdoption.id)
            .where(
                ResourceAdoption.tenant_id == actor.tenant.id,
                ResourceAdoption.member_id == actor.member.id,
                ResourceAdoption.kind == kind,
                ResourceAdoption.resource_id == resource_id,
                ResourceAdoption.version_id == version_id,
                ResourceAdoption.sha256 == sha256,
            )
            .limit(1)
        )
    )


async def record(
    db: AsyncSession,
    actor: NativeActor,
    kind: str,
    resource_id: UUID,
    version_id: UUID,
    sha256: str,
    request_id: UUID,
    expert_id: UUID | None = None,
    expert_release_id: UUID | None = None,
) -> AdoptionView:
    # Caller holds the organization lock and has checked exact proof and live authority.
    existing = await db.scalar(
        select(ResourceAdoption).where(
            ResourceAdoption.member_id == actor.member.id,
            ResourceAdoption.request_id == request_id,
        )
    )
    if existing:
        if (
            existing.kind,
            existing.resource_id,
            existing.version_id,
            existing.sha256,
            existing.expert_id,
            existing.expert_release_id,
        ) != (kind, resource_id, version_id, sha256, expert_id, expert_release_id):
            fail(409, "adoption_request_conflict", "该采用编号已用于其他内容，请核对原请求")
        return view(existing)
    row = ResourceAdoption(
        tenant_id=actor.tenant.id,
        member_id=actor.member.id,
        request_id=request_id,
        kind=kind,
        resource_id=resource_id,
        version_id=version_id,
        sha256=sha256,
        device_session_id=actor.device.id,
        expert_id=expert_id,
        expert_release_id=expert_release_id,
        created_at=now(),
    )
    db.add(row)
    await db.flush()
    return view(row)
