"""Native credentials resolve to business identity; never manufacture a Web session."""

import time
from uuid import UUID

from fastapi import Request
from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.modules.auth.service import provider
from app.modules.desktop.errors import fail
from app.modules.desktop.resources import (
    CATALOG as CATALOG,
)
from app.modules.desktop.resources import (
    NativeActor as NativeActor,
)
from app.modules.desktop.resources import (
    authorize as authorize,
)
from app.modules.desktop.resources import (
    business_actor as business_actor,
)
from app.modules.desktop.resources import (
    endpoint,
)
from app.modules.desktop.resources import (
    issue as issue,
)
from app.modules.desktop_mcp.schemas import (
    CapabilityRevision,
    ConnectionState,
    Connector,
    ConnectorRevisions,
    PersonalField,
)
from app.modules.mcp import credentials, revisions
from app.modules.mcp import service as mcp
from app.modules.mcp.models import McpConnection, McpService, McpSnapshot
from app.modules.members.service import BusinessActor


async def get_service(db: AsyncSession, actor: BusinessActor, service_id: UUID) -> McpService:
    row = await db.get(McpService, service_id, populate_existing=True)
    if not row or row.tenant_id != actor.tenant.id or not mcp.visible(row, actor):
        fail(404, "connector_unavailable", "连接器不可用或未获授权")
    return row


async def connection_state(
    request: Request, db: AsyncSession, row: McpService, actor: NativeActor
) -> ConnectionState:
    key = (row.id, credentials.owner(row, actor))
    stored = await db.get(McpConnection, key, populate_existing=True)
    snap = await db.get(McpSnapshot, key)
    checked = snap.checked_at if snap else None
    if row.auth_mode != "none" and not stored:
        action = (
            "configure"
            if row.auth_mode == "personal"
            else "authorize"
            if row.auth_mode == "oauth"
            else "contact_admin"
        )
        return ConnectionState(
            status="not_connected", action=action, error_code="credentials_required"
        )
    if row.auth_mode == "oauth" and stored:
        values = provider(request).unseal(stored.sealed)
        from app.modules.mcp.oauth_refresh import retry_state

        expired, retry = retry_state(values)
        if retry:
            return ConnectionState(
                status="error",
                action="retry",
                error_code="authorization_unavailable",
                retry_after=retry,
                checked_at=checked,
            )
        if (
            expired
            or values.get("expires_at", 0) <= time.time()
            and not values.get("refresh_token")
        ):
            return ConnectionState(
                status="reauthorization_required",
                action="authorize",
                error_code="authorization_expired",
                checked_at=checked,
            )
    if snap and snap.error:
        return ConnectionState(
            status="error",
            action="contact_admin" if row.auth_mode == "organization" else "retry",
            error_code="upstream_unavailable",
            checked_at=checked,
        )
    return ConnectionState(
        status="connected" if checked else "unverified", action="none", checked_at=checked
    )


async def connector(
    request: Request, db: AsyncSession, row: McpService, actor: NativeActor
) -> Connector:
    caps = await mcp.capability_view(db, row, actor)
    exposed = [
        {
            "kind": c.kind,
            "key": c.key,
            "enabled": c.enabled,
            "contract_revision": revisions.contract(c.model_dump(), caps.protocol),
            "behavior_revision": revisions.behavior(
                {"definition": c.definition, "description": c.original_description},
                await revisions.source_body(db, row, {"kind": c.kind, "key": c.key}),
            ),
        }
        for c in caps.items
    ]
    exposed.sort(key=lambda c: (c["kind"], c["key"]))
    return Connector(
        id=row.id,
        name=row.name,
        display_name=row.display_name or row.name,
        description=row.description,
        icon=row.icon,
        examples=row.examples,
        auth_mode=row.auth_mode,
        credential_fields=[
            PersonalField(key=f["key"], label=f["label"]) for f in row.credential_fields
        ]
        if row.auth_mode == "personal"
        else [],
        connection=await connection_state(request, db, row, actor),
        counts={
            k: sum(c.kind == k for c in caps.items)
            for k in ("tools", "prompts", "resources", "templates")
        },
        revisions=ConnectorRevisions(
            display=revisions.display(row),
            connection=revisions.connection(row),
            authorization=revisions.authorization(row, exposed, str(actor.member.id)),
            capabilities=revisions.digest(
                [(c["kind"], c["key"], c["contract_revision"]) for c in exposed]
            ),
            behavior=revisions.digest(
                [(c["kind"], c["key"], c["behavior_revision"]) for c in exposed]
            ),
        ),
        capability_revisions=[CapabilityRevision(**c) for c in exposed],
        endpoint=endpoint(request, "mcp:" + str(row.id)),
    )


def visibility(actor: NativeActor) -> tuple[ColumnElement[bool], ...]:
    # Desktop use never inherits the console administrator test bypass.
    return (
        McpService.tenant_id == actor.tenant.id,
        McpService.enabled.is_(True),
        or_(
            McpService.audience == "organization",
            McpService.member_ids.contains([str(actor.member.id)]),
        ),
    )
