"""Idempotent administrator diagnostic admission and metadata lookup."""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import UUID

from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter
from sqlalchemy import select

from app.modules.audit.models import AuditEvent
from app.modules.auth.service import DB, provider
from app.modules.llm.channel_testing import RecoveryIdentity, admit, project_record, run
from app.modules.llm.diagnostic_schemas import DiagnosticDetail, DiagnosticRequest
from app.modules.llm.models import ModelCall
from app.modules.llm.router import administrator, channel
from app.modules.llm.schemas import ChannelChatProbe, ChannelProbe, ChannelTestView

_PROBE: TypeAdapter[ChannelProbe] = TypeAdapter(ChannelProbe)


def digest(request: Request, body: DiagnosticRequest) -> str:
    """Authenticate the full request without persisting input text or media."""
    secret = provider(request).settings.session_encryption_key
    if secret is None:
        raise HTTPException(503, "管理回执密钥尚未配置")
    data = json.dumps(
        body.model_dump(mode="json", exclude={"request_id"}),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hmac.new(secret.get_secret_value().encode(), data.encode(), hashlib.sha256).hexdigest()


async def run_diagnostic(
    channel_id: UUID, request: Request, db: DB, body: DiagnosticRequest
) -> ChannelTestView | StreamingResponse:
    # Authenticate before deriving a secret-backed receipt, even if the shared
    # run path will recheck admission immediately before its database write.
    await administrator(request, db, write=True)
    payload = {
        "version": body.version,
        "id": body.upstream_id,
        "operation": body.operation,
        **body.input.model_dump(exclude_none=True),
    }
    probe = _PROBE.validate_python(payload)
    certification = (
        RecoveryIdentity(body.model_id, body.model_version, body.binding_id)
        if body.certify_health
        and body.model_id is not None
        and body.model_version is not None
        and body.binding_id is not None
        else None
    )
    receipt = digest(request, body)
    if body.stream:
        if not isinstance(probe, ChannelChatProbe):
            raise HTTPException(422, "仅对话诊断支持流式输出")
        from app.modules.llm.diagnostic_stream import stream_response

        admitted = await admit(
            channel_id,
            request,
            db,
            probe,
            request_id=body.request_id,
            request_digest=receipt,
            certification=certification,
            stream=True,
        )
        return stream_response(request, admitted, probe)
    return await run(
        channel_id,
        request,
        db,
        probe,
        request_id=body.request_id,
        request_digest=receipt,
        certification=certification,
    )


async def diagnostic_detail(request_id: UUID, request: Request, db: DB) -> DiagnosticDetail:
    actor = await administrator(request, db)
    starts = list(
        await db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == actor.tenant.id,
                AuditEvent.action == "llm.channel.test.start",
                AuditEvent.details["request_id"].as_string() == str(request_id),
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(2)
        )
    )
    if len(starts) != 1:
        raise HTTPException(404, "诊断记录不存在")
    start = starts[0]
    row = await channel(db, actor, start.target_id)
    finish = await db.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == actor.tenant.id,
            AuditEvent.target_id == row.id,
            AuditEvent.action == "llm.channel.test.finish",
            AuditEvent.details["request_id"].as_string() == str(request_id),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    call = await db.scalar(
        select(ModelCall).where(
            ModelCall.id == request_id,
            ModelCall.tenant_id == actor.tenant.id,
            ModelCall.channel_id == row.id,
            ModelCall.source == "channel_diagnostic",
        )
    )
    return DiagnosticDetail(
        channel_id=row.id,
        record=project_record(
            start, finish, call, current_version=row.version, archived=row.archived
        ),
    )
