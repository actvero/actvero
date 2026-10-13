"""Read-only inventory references and guarded removal under the tenant write lock."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ReferencedResourceConflict
from app.modules.audit.models import AuditEvent
from app.modules.llm import routing
from app.modules.llm.binding_identity import projected_binding_id
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import CatalogModel, ModelCall, ModelChannel
from app.modules.llm.schemas import (
    ChannelBindingReference,
    ChannelRemovalReference,
    LatestChannelDiagnostic,
)


async def assert_inventory_removable(
    db: AsyncSession, channel: ModelChannel, removed: set[str]
) -> None:
    if not removed:
        return
    references = []
    # The caller holds the same organization lock as model configuration writes.
    # Protect enabled bindings even when the model/operation/channel is temporarily off.
    with db.no_autoflush:
        models = await db.scalars(
            select(CatalogModel).where(
                CatalogModel.tenant_id == channel.tenant_id, CatalogModel.archived.is_(False)
            )
        )
        for model in models:
            config = CatalogInput.model_validate(model.configuration)
            for operation in config.operation_configs():
                for binding in operation.bindings:
                    if (
                        binding.channel_id == channel.id
                        and binding.upstream_id in removed
                        and binding.enabled
                    ):
                        references.append(
                            ChannelRemovalReference(
                                model_id=model.id,
                                model_name=model.name,
                                operation=operation.kind,
                                binding_id=projected_binding_id(model.id, operation.kind, binding),
                            ).model_dump(mode="json")
                        )
    if references:
        raise ReferencedResourceConflict("上游模型被启用绑定引用，请先停用对应绑定", references)


async def project_binding_references(
    db: AsyncSession, channel: ModelChannel
) -> list[ChannelBindingReference]:
    result = []
    registered = {item["id"] for item in channel.models}
    with db.no_autoflush:
        models = await db.scalars(
            select(CatalogModel)
            .where(CatalogModel.tenant_id == channel.tenant_id)
            .order_by(CatalogModel.name, CatalogModel.id)
        )
        for model in models:
            config = CatalogInput.model_validate(model.configuration)
            for operation in config.operation_configs():
                execution = config.for_operation(operation.kind)
                assert execution is not None
                for binding in operation.bindings:
                    if binding.channel_id != channel.id:
                        continue
                    health = None
                    if model.archived:
                        status = "model_archived"
                    elif not config.access.enabled:
                        status = "model_disabled"
                    elif not operation.enabled:
                        status = "operation_disabled"
                    else:
                        status, health = await routing.state(
                            db,
                            channel.tenant_id,
                            model.id,
                            execution,
                            binding,
                            channel,
                            require_test=operation.routing.mode == "auto",
                            ignore_manual_enabled=True,
                        )
                    result.append(
                        ChannelBindingReference(
                            model_version=model.version,
                            model_id=model.id,
                            model_name=model.name,
                            operation=operation.kind,
                            binding_id=projected_binding_id(model.id, operation.kind, binding),
                            upstream_model_id=binding.upstream_id,
                            binding_enabled=binding.enabled,
                            operation_enabled=operation.enabled,
                            model_enabled=config.access.enabled,
                            model_archived=model.archived,
                            source_registered=binding.upstream_id in registered,
                            health_state=status,
                            health_block_reason=health.block_reason if health else None,
                            cooldown_until=health.cooldown_until if health else None,
                            tested_at=health.tested_at if health else None,
                        )
                    )
    return result


async def project_latest_diagnostics(
    db: AsyncSession, channels: Sequence[ModelChannel]
) -> dict[UUID, LatestChannelDiagnostic]:
    """Latest started diagnostic, including missing finishes, without outputs or secrets."""
    from app.modules.llm.channel_testing import project_record

    result = {}
    by_id = {row.id: row for row in channels}
    with db.no_autoflush:
        for tenant_id in {row.tenant_id for row in channels}:
            channel_ids = [row.id for row in channels if row.tenant_id == tenant_id]
            starts = list(
                await db.scalars(
                    select(AuditEvent)
                    .where(
                        AuditEvent.tenant_id == tenant_id,
                        AuditEvent.target_id.in_(channel_ids),
                        AuditEvent.action == "llm.channel.test.start",
                    )
                    .distinct(AuditEvent.target_id)
                    .order_by(
                        AuditEvent.target_id, AuditEvent.created_at.desc(), AuditEvent.id.desc()
                    )
                )
            )
            if not starts:
                continue
            finishes = await db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.target_id.in_(channel_ids),
                    AuditEvent.action == "llm.channel.test.finish",
                    AuditEvent.details["request_id"]
                    .as_string()
                    .in_([event.details.get("request_id", "") for event in starts]),
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
            lookup = {
                (event.target_id, event.details.get("request_id")): event for event in finishes
            }
            calls = await db.scalars(
                select(ModelCall).where(
                    ModelCall.tenant_id == tenant_id,
                    ModelCall.channel_id.in_(channel_ids),
                    ModelCall.source == "channel_diagnostic",
                    ModelCall.id.in_([UUID(event.details["request_id"]) for event in starts]),
                )
            )
            call_lookup = {(call.channel_id, str(call.id)): call for call in calls}
            for event in starts:
                details = event.details
                request_id = details.get("request_id", "")
                finish = lookup.get((event.target_id, request_id))
                channel = by_id[event.target_id]
                record = project_record(
                    event,
                    finish,
                    call_lookup.get((channel.id, request_id)),
                    current_version=channel.version,
                    archived=channel.archived,
                )
                result[channel.id] = LatestChannelDiagnostic(
                    at=record.tested_at,
                    ok=record.status == "success" if record.status != "unconfirmed" else None,
                    status=record.status,
                    operation=record.operation,
                    upstream_model_id=record.model,
                    request_id=record.request_id,
                    duration_ms=record.duration_ms,
                    channel_version=record.channel_version,
                    stale=record.stale,
                )
    return result
