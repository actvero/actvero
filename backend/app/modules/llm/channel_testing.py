"""Bounded administrator diagnostics; reuse runtime adapters without publishing models."""

import asyncio
import time
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

import anyio
from fastapi import HTTPException, Request
from sqlalchemy import String, case, cast, or_, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import aliased

from app.core.config import Settings
from app.modules.audit.models import AuditEvent
from app.modules.auth.service import DB, limit, now, provider
from app.modules.llm.catalog_schemas import RetrievalOptions
from app.modules.llm.diagnostic_health import RecoveryLease
from app.modules.llm.image_delivery import deliver_image
from app.modules.llm.inference_schemas import (
    EmbeddingInput,
    EmbeddingOutput,
    RerankInput,
    RerankOutput,
)
from app.modules.llm.models import ModelCall
from app.modules.llm.providers import PROVIDERS, retrieval
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.providers.connection import OperationTarget, resolve_stored_connection
from app.modules.llm.router import administrator, channel, editable
from app.modules.llm.schemas import (
    ChannelChatProbe,
    ChannelEmbeddingProbe,
    ChannelImageProbe,
    ChannelProbe,
    ChannelSpeechProbe,
    ChannelTestRecord,
    ChannelTestView,
    RankPreview,
    VectorPreview,
)
from app.modules.members.service import record
from app.modules.tenants.models import Tenant


@dataclass(frozen=True)
class RecoveryIdentity:
    model_id: UUID
    model_version: int
    binding_id: UUID


@dataclass(frozen=True)
class DiagnosticAdmission:
    request_id: UUID
    tenant_id: UUID
    channel_id: UUID
    channel_version: int
    metadata: dict[str, str]
    trace: AttemptTrace
    lease: RecoveryLease | None
    adapter: str
    base: str
    key: str | None
    timeout: int
    target: OperationTarget | None


async def execute(
    body: ChannelProbe,
    *,
    adapter: str,
    base: str,
    key: str | None,
    timeout: int,
    settings: Settings,
    request_id: UUID,
    target: OperationTarget | None = None,
    trace: AttemptTrace | None = None,
) -> ChannelTestView:
    if isinstance(body, ChannelChatProbe):
        from app.modules.llm.providers.sdk import test_chat

        return await test_chat(
            adapter=adapter,
            base=base,
            key=key,
            model=body.id,
            prompt=body.prompt,
            max_output=body.max_output_tokens,
            timeout=timeout,
            settings=settings,
            request_id=request_id,
            target=target,
            trace=trace,
        )
    started = time.monotonic()
    result = ChannelTestView(
        operation=body.operation,
        ok=False,
        message="测试失败",
        request_id=request_id,
        tested_at=now(),
        duration_ms=0,
    )
    if isinstance(body, ChannelSpeechProbe):
        from app.modules.llm.providers.sdk_speech import generate as speech

        try:
            result.audio = await speech(
                body, base, key, timeout, settings, target=target, trace=trace
            )
            result.audio_duration_ms = result.audio.duration_ms
            result.ok, result.message = True, "语音生成成功"
        except retrieval.UpstreamFailure as exc:
            result.message, result.error_code, result.uncertain = (
                str(exc.detail),
                exc.code,
                exc.uncertain,
            )
        except HTTPException:
            result.error_code, result.message = "request_rejected", "请求被出站规则拒绝或参数无效"
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result
    if isinstance(body, ChannelImageProbe):
        from app.modules.llm.providers.sdk_images import generate

        try:
            generated = await generate(
                body, base, key, timeout, settings, target=target, trace=trace
            )
            result.input_tokens = generated.usage["input_tokens"]
            result.output_tokens = generated.usage["output_tokens"]
            if all(v is not None for v in generated.usage.values()):
                result.usage_source = "upstream"
            result.image = await deliver_image(generated.image, settings)
            result.image_count = 1
            if trace is not None:
                trace.observe_usage({"image_count": 1})
            result.ok, result.message = True, "图片生成成功"
        except retrieval.UpstreamFailure as exc:
            result.message, result.error_code, result.uncertain = (
                str(exc.detail),
                exc.code,
                exc.uncertain,
            )
        except HTTPException:
            result.error_code, result.message = "request_rejected", "请求被出站规则拒绝或参数无效"
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result
    embedding = isinstance(body, ChannelEmbeddingProbe)
    request_body: EmbeddingInput | RerankInput
    if isinstance(body, ChannelEmbeddingProbe):
        request_body = EmbeddingInput(model=body.id, input=body.input, dimensions=body.dimensions)
        dimensions = body.dimensions
    else:
        request_body = RerankInput(
            model=body.id, query=body.query, documents=body.documents, top_n=body.top_n
        )
        dimensions = None
    # Explicit diagnostic dimensions never change saved model capabilities.
    limits = RetrievalOptions(
        max_batch_size=8,
        max_input_characters=18000,
        dimensions=dimensions,
        dimension_options=[dimensions] if dimensions else [],
    )
    received = False
    try:
        path, payload, _ = retrieval.prepare(request_body, limits, body.id)
        raw = await retrieval.post(
            base, path, key, timeout, settings, payload, target=target, trace=trace
        )
        received = True
        output, usage = retrieval.normalize(raw, request_body, limits, str(request_id))
        if trace is not None:
            trace.mark_upstream_terminal()
            trace.observe_usage(usage)
        result.ok = True
        result.message = "向量测试成功" if embedding else "重排测试成功"
        result.input_tokens = usage.get("input_tokens")
        result.search_units = usage.get("search_units")
        result.usage_source = usage["source"]
        if isinstance(output, EmbeddingOutput):
            result.vectors = [
                VectorPreview(index=v.index, dimensions=len(v.embedding), values=v.embedding[:8])
                for v in output.data
            ]
        elif isinstance(output, RerankOutput):
            result.ranks = [RankPreview(**r.model_dump()) for r in output.results]
    except retrieval.UpstreamFailure as exc:
        result.message, result.error_code, result.uncertain = (
            str(exc.detail),
            exc.code,
            exc.uncertain or exc.code == "invalid_upstream_response",
        )
    except HTTPException:
        result.uncertain = received
        result.error_code = "invalid_upstream_response" if received else "request_rejected"
        result.message = "上游返回结果格式无效" if received else "请求被出站规则拒绝或参数无效"
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result


async def finish_diagnostic(
    request: Request,
    tenant_id: UUID,
    call_id: UUID,
    trace: AttemptTrace,
    result: ChannelTestView | None,
    *,
    error: BaseException | None = None,
    cancelled: bool = False,
    lease: RecoveryLease | None = None,
) -> None:
    """Commit execution evidence before potentially blocked health cleanup."""
    evidence = trace.finish(error=error, cancelled=cancelled)
    if lease is not None:
        evidence["health_certification"] = "not_certified"
        evidence["health_cleanup"] = "lease_expiry_pending"
        if result is not None:
            result.health_certification = "not_certified"
    async with request.app.state.database.sessions() as cleanup:
        call = await cleanup.get(ModelCall, call_id)
        if call is None or call.tenant_id != tenant_id or call.source != "channel_diagnostic":
            return
        if call.status != "pending":
            return
        # Admission was committed before dispatch. No model/health/settlement is changed.
        call.attempts = [{**call.attempts[0], **evidence}]
        call.status = (
            "unknown"
            if cancelled or result is None or (result.stream and not trace.upstream_terminal)
            else "succeeded"
            if result.ok
            else "failed"
        )
        call.error_code = (
            "caller_cancelled"
            if cancelled
            else result.error_code
            if result
            else evidence.get("error_code")
        )
        call.termination_code = call.error_code
        call.duration_ms = evidence.get("duration_ms")
        if result is not None:
            call.usage = {
                "source": result.usage_source,
                **{
                    name: getattr(result, name)
                    for name in ("input_tokens", "output_tokens", "search_units", "image_count")
                    if getattr(result, name) is not None
                },
            }
        await cleanup.commit()
    if lease is None:
        return

    from app.modules.llm.diagnostic_health import finish_recovery, release_recovery

    # A contended tenant lock must not erase already-committed execution
    # evidence. Run this short transaction in its own task so a direct
    # asyncio.Task.cancel cannot interrupt asyncpg halfway through rollback.
    abort_certification = asyncio.Event()

    async def clean_health() -> None:
        certified = False
        try:
            async with request.app.state.database.sessions() as cleanup:
                await cleanup.execute(text("SET LOCAL lock_timeout = '1500ms'"))
                await cleanup.scalar(
                    select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
                )
                if cancelled or result is None or abort_certification.is_set():
                    await release_recovery(cleanup, lease)
                else:
                    certified = await finish_recovery(cleanup, lease, result=result)
                    if abort_certification.is_set():
                        await cleanup.rollback()
                        return  # The lease may expire; do not certify a cancelled request.
                if abort_certification.is_set() and not (cancelled or result is None):
                    await cleanup.rollback()
                    return
                call = await cleanup.get(ModelCall, call_id)
                if call is not None and call.tenant_id == tenant_id:
                    attempt = dict(call.attempts[0])
                    attempt["health_cleanup"] = "certified" if certified else "completed"
                    if certified:
                        attempt["health_certification"] = "certified"
                    call.attempts = [attempt]
                else:
                    certified = False
                await cleanup.commit()
            if result is not None and not cancelled and certified:
                result.health_certification = "certified"
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != "55P03":
                raise

    cleanup_task = asyncio.create_task(clean_health())
    try:
        await asyncio.shield(cleanup_task)
    except asyncio.CancelledError:
        abort_certification.set()
        # The local lock timeout is 1.5s; allow 2.5s for rollback and
        # connection return before propagating cancellation to the HTTP layer.
        try:
            await asyncio.wait_for(asyncio.shield(cleanup_task), 2.5)
        except TimeoutError:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
        except Exception:
            pass  # The already-committed attempt remains authoritative.
        raise


async def admit(
    channel_id: UUID,
    request: Request,
    db: DB,
    body: ChannelProbe,
    *,
    request_id: UUID | None = None,
    request_digest: str | None = None,
    certification: RecoveryIdentity | None = None,
    stream: bool = False,
) -> DiagnosticAdmission:
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    editable(row)
    if not any(m["id"] == body.id for m in row.models):
        raise HTTPException(422, "请先保存要测试的上游模型")
    module = PROVIDERS[row.provider]
    if body.operation not in module.info.test_operations:
        raise HTTPException(422, "此供应商尚未接入该测试接口")
    if request_id is not None and await db.get(ModelCall, request_id) is not None:
        raise HTTPException(409, "此诊断请求标识已被使用，请查询诊断详情")
    connection_value = getattr(row, "connection", None)
    target = None
    if connection_value is not None and connection_value != {}:
        try:
            target = resolve_stored_connection(
                row.provider,
                row.base_url,
                connection_value,
                model=body.id,
                operations=(body.operation,),
                stream=stream,
            ).operation_targets[0]
        except ValueError as exc:
            raise HTTPException(422, "渠道地址或测试操作配置无效") from exc
    await limit(db, f"channel-test:{actor.tenant.id}:{actor.user.id}", maximum=10, seconds=60)
    # limit commits its counter and releases the tenant lock. A channel edit,
    # archive, or membership change may commit in that gap; reacquire the lock
    # and refresh every dispatch-affecting field before creating the receipt.
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, channel_id, body.version)
    editable(row)
    if not any(m["id"] == body.id for m in row.models):
        raise HTTPException(422, "请先保存要测试的上游模型")
    module = PROVIDERS[row.provider]
    if body.operation not in module.info.test_operations:
        raise HTTPException(422, "此供应商尚未接入该测试接口")
    connection_value = getattr(row, "connection", None)
    target = None
    if connection_value is not None and connection_value != {}:
        try:
            target = resolve_stored_connection(
                row.provider,
                row.base_url,
                connection_value,
                model=body.id,
                operations=(body.operation,),
                stream=stream,
            ).operation_targets[0]
        except ValueError as exc:
            raise HTTPException(422, "渠道地址或测试操作配置无效") from exc
    key = str(provider(request).unseal(row.sealed_key)["key"]) if row.sealed_key else None
    base, timeout, version = row.base_url, row.timeout_seconds, row.version
    request_id = request_id or uuid4()
    trace = AttemptTrace(str(request_id))
    lease: RecoveryLease | None = None
    if certification is not None:
        from app.modules.llm.diagnostic_health import begin_recovery

        await db.scalar(select(Tenant).where(Tenant.id == actor.tenant.id).with_for_update())
        lease = await begin_recovery(
            db,
            tenant_id=actor.tenant.id,
            actor_member_id=actor.member.id,
            model_id=certification.model_id,
            model_version=certification.model_version,
            binding_id=certification.binding_id,
            channel_id=row.id,
            channel_version=version,
            body=body,
            stream=stream,
        )
    metadata = {
        "request_id": str(request_id),
        "model": body.id,
        "operation": body.operation,
        "channel_version": str(version),
        "stream": str(stream).lower(),
    }
    if isinstance(body, ChannelImageProbe):
        metadata.update(
            {
                name: str(value)
                for name, value in body.model_dump(
                    include={"size", "quality"}, exclude_none=True
                ).items()
            }
        )
    record(db, actor, "llm.channel.test.start", row.id, row.name, metadata)
    db.add(
        ModelCall(
            id=request_id,
            tenant_id=actor.tenant.id,
            model_id=None,
            channel_id=row.id,
            actor_id=actor.user.id,
            source="channel_diagnostic",
            kind=body.operation,
            status="pending",
            attempts=[
                {
                    "number": 1,
                    "channel_id": str(row.id),
                    "channel_version": version,
                    "operation": body.operation,
                    "stream": stream,
                    "upstream_id": body.id,
                    "started_at": now().isoformat(),
                    **({"request_digest": request_digest} if request_digest is not None else {}),
                    **trace.snapshot(),
                }
            ],
        )
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if request_digest is None or getattr(exc.orig, "sqlstate", None) != "23505":
            raise
        raise HTTPException(409, "此诊断请求标识已被使用，请查询诊断详情") from exc
    return DiagnosticAdmission(
        request_id=request_id,
        tenant_id=actor.tenant.id,
        channel_id=row.id,
        channel_version=version,
        metadata=metadata,
        trace=trace,
        lease=lease,
        adapter=module.sdk_provider,
        base=base,
        key=key,
        timeout=timeout,
        target=target,
    )


async def persist_result(
    request: Request, admitted: DiagnosticAdmission, result: ChannelTestView
) -> None:
    """Save a completed attempt before any response or optional audit projection."""
    trace = admitted.trace
    if result.ok and not result.stream:
        trace.mark_output()
    failure = (
        None
        if result.ok or trace.error_code is not None
        else retrieval.UpstreamFailure(
            502,
            result.error_code or "upstream_error",
            "渠道诊断失败",
            uncertain=result.uncertain,
        )
    )
    await finish_diagnostic(
        request,
        admitted.tenant_id,
        admitted.request_id,
        trace,
        result,
        error=failure,
        lease=admitted.lease,
    )
    result.attempt = trace.snapshot()


async def audit_result(
    request: Request, db: DB, admitted: DiagnosticAdmission, result: ChannelTestView
) -> None:
    """Recheck the current administrator and channel before releasing a result."""
    actor = await administrator(request, db, write=True)
    row = await channel(db, actor, admitted.channel_id)
    record(
        db,
        actor,
        "llm.channel.test.finish",
        row.id,
        row.name,
        {
            **admitted.metadata,
            "current_version": str(row.version),
            **{
                field: str(getattr(result, field))
                for field in (
                    "duration_ms",
                    "usage_source",
                    "input_tokens",
                    "output_tokens",
                    "search_units",
                    "image_count",
                    "audio_duration_ms",
                    "uncertain",
                    "error_code",
                )
            },
        },
        result="success" if result.ok else "failure",
    )
    await db.commit()
    if row.version != admitted.channel_version or row.archived:
        raise HTTPException(409, "测试期间渠道已修改，结果已记入测试记录，请刷新后核对")


async def run(
    channel_id: UUID,
    request: Request,
    db: DB,
    body: ChannelProbe,
    *,
    request_id: UUID | None = None,
    request_digest: str | None = None,
    certification: RecoveryIdentity | None = None,
) -> ChannelTestView:
    admitted = await admit(
        channel_id,
        request,
        db,
        body,
        request_id=request_id,
        request_digest=request_digest,
        certification=certification,
    )
    request_id, trace, lease = admitted.request_id, admitted.trace, admitted.lease
    tenant_id = admitted.tenant_id
    try:
        result = await execute(
            body,
            adapter=admitted.adapter,
            base=admitted.base,
            key=admitted.key,
            timeout=admitted.timeout,
            settings=provider(request).settings,
            request_id=request_id,
            target=admitted.target,
            trace=trace,
        )
        await persist_result(request, admitted, result)
    except (asyncio.CancelledError, GeneratorExit):
        with anyio.move_on_after(3, shield=True):
            await finish_diagnostic(
                request, tenant_id, request_id, trace, None, cancelled=True, lease=lease
            )
        raise
    except Exception as exc:
        with anyio.move_on_after(3, shield=True):
            await finish_diagnostic(
                request, tenant_id, request_id, trace, None, error=exc, lease=lease
            )
        raise
    await audit_result(request, db, admitted, result)
    return result


def integer(value: str | None) -> int | None:
    return int(value) if value is not None and value.isdigit() else None


def project_record(
    start: AuditEvent,
    finish: AuditEvent | None,
    call: ModelCall | None,
    *,
    current_version: int,
    archived: bool,
) -> ChannelTestRecord:
    details = {**start.details, **(finish.details if finish else {})}
    version = integer(details.get("channel_version"))
    attempt = dict(call.attempts[0]) if call and call.attempts else None
    if attempt is not None:
        attempt.pop("request_digest", None)
    stream_value = details.get("stream")
    stream = (
        stream_value == "true"
        if stream_value in ("true", "false")
        else attempt.get("stream")
        if attempt and type(attempt.get("stream")) is bool
        else None
    )
    # The metadata call may have committed before a later authorization check
    # rejected the HTTP response; historic audit-only rows remain unknown.
    if call is not None:
        details.update({name: str(value) for name, value in call.usage.items()})
        details["duration_ms"] = str(call.duration_ms)
        details["error_code"] = str(call.error_code)
    status: Literal["success", "failure", "unconfirmed"] = (
        (
            "success"
            if call.status == "succeeded"
            else "failure"
            if call.status == "failed"
            else "unconfirmed"
        )
        if call
        else ("success" if finish.result == "success" else "failure")
        if finish
        else "unconfirmed"
    )
    return ChannelTestRecord(
        request_id=details["request_id"],
        model=details["model"],
        operation=details.get("operation", "chat"),
        stream=stream,
        tested_at=start.created_at,
        status=status,
        duration_ms=integer(details.get("duration_ms")),
        channel_version=version,
        stale=version is None or version != current_version or archived,
        input_tokens=integer(details.get("input_tokens")),
        output_tokens=integer(details.get("output_tokens")),
        search_units=integer(details.get("search_units")),
        image_count=integer(details.get("image_count")),
        audio_duration_ms=integer(details.get("audio_duration_ms")),
        uncertain=attempt.get("uncertain", True)
        if attempt
        else finish is None or details.get("uncertain") == "True",
        error_code=details.get("error_code") if details.get("error_code") != "None" else None,
        record_version="attempt_v1" if call else "legacy_audit",
        health_certification=attempt.get("health_certification", "not_requested")
        if attempt
        else "not_requested",
        attempt=attempt,
    )


async def history(
    channel_id: UUID,
    request: Request,
    db: DB,
    page: int,
    *,
    operation: str | None = None,
    status: str | None = None,
    channel_version: int | None = None,
) -> list[ChannelTestRecord]:
    actor = await administrator(request, db)
    row = await channel(db, actor, channel_id)
    starts_query = select(AuditEvent).where(
        AuditEvent.tenant_id == actor.tenant.id,
        AuditEvent.target_id == channel_id,
        AuditEvent.action == "llm.channel.test.start",
    )
    if operation is not None:
        actual = AuditEvent.details["operation"].as_string()
        starts_query = starts_query.where(
            or_(actual == operation, actual.is_(None))
            if operation == "chat"
            else actual == operation
        )
    if channel_version is not None:
        starts_query = starts_query.where(
            AuditEvent.details["channel_version"].as_string() == str(channel_version)
        )
    if status is not None:
        finish_row = aliased(AuditEvent)
        audit_id = AuditEvent.details["request_id"].as_string()
        call_status = (
            select(ModelCall.status)
            .where(
                ModelCall.tenant_id == actor.tenant.id,
                ModelCall.channel_id == channel_id,
                ModelCall.source == "channel_diagnostic",
                cast(ModelCall.id, String) == audit_id,
            )
            .limit(1)
            .scalar_subquery()
        )
        finish_result = (
            select(finish_row.result)
            .where(
                finish_row.tenant_id == actor.tenant.id,
                finish_row.target_id == channel_id,
                finish_row.action == "llm.channel.test.finish",
                finish_row.details["request_id"].as_string() == audit_id,
            )
            .limit(1)
            .scalar_subquery()
        )
        status_value = case(
            (call_status == "succeeded", "success"),
            (call_status == "failed", "failure"),
            (call_status.is_not(None), "unconfirmed"),
            (finish_result == "success", "success"),
            (finish_result.is_not(None), "failure"),
            else_="unconfirmed",
        )
        starts_query = starts_query.where(status_value == status)
    starts = list(
        await db.scalars(
            starts_query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .offset((page - 1) * 20)
            .limit(20)
        )
    )
    if not starts:
        return []
    ids = [event.details["request_id"] for event in starts]
    finishes = await db.scalars(
        select(AuditEvent).where(
            AuditEvent.tenant_id == actor.tenant.id,
            AuditEvent.target_id == channel_id,
            AuditEvent.action == "llm.channel.test.finish",
            AuditEvent.details["request_id"].as_string().in_(ids),
        )
    )
    lookup = {event.details["request_id"]: event for event in finishes}
    calls = await db.scalars(
        select(ModelCall).where(
            ModelCall.tenant_id == actor.tenant.id,
            ModelCall.channel_id == channel_id,
            ModelCall.source == "channel_diagnostic",
            ModelCall.id.in_([UUID(value) for value in ids]),
        )
    )
    evidence_by_id = {str(call.id): call for call in calls}
    return [
        project_record(
            start,
            lookup.get(start.details["request_id"]),
            evidence_by_id.get(start.details["request_id"]),
            current_version=row.version,
            archived=row.archived,
        )
        for start in starts
    ]
