"""Read-only channel health projection from enabled model bindings."""

from collections import Counter
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now
from app.modules.llm import routing
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.models import CatalogModel, ModelChannel
from app.modules.llm.schemas import ChannelHealthSummary, HealthSummaryState


async def project_channel_health(
    db: AsyncSession, rows: Sequence[ModelChannel]
) -> dict[UUID, ChannelHealthSummary]:
    """Summarize binding facts without refreshing, claiming or creating health rows."""
    as_of = now()
    if not rows:
        return {}

    by_id = {channel.id: channel for channel in rows}
    counts: dict[UUID, Counter[str]] = {channel_id: Counter() for channel_id in by_id}
    # Avoid even an incidental flush from this read projection.
    with db.no_autoflush:
        for tenant_id in {channel.tenant_id for channel in rows}:
            models = await db.execute(
                select(CatalogModel.id, CatalogModel.configuration).where(
                    CatalogModel.tenant_id == tenant_id, CatalogModel.archived.is_(False)
                )
            )
            for model_id, payload in models:
                config = CatalogInput.model_validate(payload)
                if not config.access.enabled:
                    continue
                for operation in config.operation_configs():
                    if not operation.enabled:
                        continue
                    execution = config.for_operation(operation.kind)
                    assert execution is not None
                    for binding in operation.bindings:
                        channel = by_id.get(binding.channel_id)
                        if (
                            channel is None
                            or channel.tenant_id != tenant_id
                            or channel.archived
                            or not binding.enabled
                        ):
                            continue
                        status, _ = await routing.state(
                            db,
                            tenant_id,
                            model_id,
                            execution,
                            binding,
                            channel,
                            require_test=operation.routing.mode == "auto",
                            ignore_manual_enabled=True,
                        )
                        counts[channel.id][status] += 1

    result = {}
    for channel_id, channel in by_id.items():
        health_counts = dict(counts[channel_id])
        ready = health_counts.get("ready", 0)
        total = sum(health_counts.values())
        if channel.archived:
            state: HealthSummaryState = "not_applicable"
        elif total == 0:
            state = "no_routes"
        elif ready == total:
            state = "ready"
        elif ready:
            state = "degraded"
        elif any(key != "unverified" for key in health_counts):
            state = "unavailable"
        else:
            state = "unverified"
        result[channel_id] = ChannelHealthSummary(
            state=state, health_counts=health_counts, as_of=as_of
        )
    return result
