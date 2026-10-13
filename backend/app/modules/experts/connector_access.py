"""Expert-specific tool restrictions intersect the existing MCP runtime authorization."""

from typing import Any, cast
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import provider
from app.modules.desktop.errors import fail
from app.modules.experts.models import ExpertRecord, ExpertRelease
from app.modules.experts.service import allowed
from app.modules.members.service import BusinessActor


def connector_endpoint(
    request: Request, service_id: UUID, expert_id: UUID, release_id: UUID, key: str
) -> str:
    return (
        provider(request).settings.app_url.rstrip("/")
        + f"/api/mcp/services/{service_id}/experts/{expert_id}/releases/{release_id}/{key}"
    )


async def reference(
    db: AsyncSession,
    actor: BusinessActor,
    service_id: UUID,
    expert_id: UUID,
    release_id: UUID,
    key: str,
) -> dict[str, Any]:
    expert = await db.get(ExpertRecord, expert_id, populate_existing=True)
    if (
        not expert
        or expert.tenant_id != actor.tenant.id
        or not expert.current_release_id
        or not allowed(expert.audience, expert.member_ids, actor.member)
    ):
        fail(404, "expert_unavailable", "专家不可用或未获授权")
    release = await db.get(ExpertRelease, release_id)
    if not release or release.expert_id != expert.id:
        fail(404, "expert_release_unavailable", "专家发布不可用")
    ref = next(
        (
            r
            for r in release.dependency_refs["connectors"]
            if r["key"] == key and r["connector_id"] == str(service_id)
        ),
        None,
    )
    if ref is None:
        fail(404, "expert_connector_unavailable", "此发布未配置该连接器")
    # Old sessions retain their immutable release policy. Live expert/source permission
    # and withdrawal are still checked on every request; draft edits never affect them.
    return cast(dict[str, Any], ref)


async def allowed_tools(
    db: AsyncSession,
    actor: BusinessActor,
    service_id: UUID,
    expert_id: UUID,
    release_id: UUID,
    key: str,
) -> set[str] | None:
    ref = await reference(db, actor, service_id, expert_id, release_id, key)
    return set(ref["tools"]) if ref.get("tools") is not None else None
