"""Give existing model bindings stable IDs without changing execution evidence."""

import json
from copy import deepcopy
from typing import Any
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op

revision = "93n_model_binding_ids"
down_revision = "92m_merge_skills_gateway"
branch_labels = None
depends_on = None

# Frozen migration algorithm: do not import a runtime helper that can change later.
BINDING_NAMESPACE = UUID("57f64cb7-0847-5c90-a40b-e34596bb325d")


def legacy_binding_id(model_id: UUID, operation: str, channel_id: UUID, upstream_id: str) -> UUID:
    value = json.dumps(
        [str(model_id), operation, str(channel_id), upstream_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return uuid5(BINDING_NAMESPACE, value)


def backfill_configuration(model_id: UUID, configuration: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(configuration)
    identities: dict[tuple[str, UUID, str], str] = {}

    def populate(kind: str, bindings: list[dict[str, Any]]) -> None:
        for binding in bindings:
            key = (kind, UUID(str(binding["channel_id"])), binding["upstream_id"])
            existing = binding.get("binding_id")
            identifier = str(UUID(existing)) if existing else identities.get(key)
            if identifier is None:
                identifier = str(legacy_binding_id(model_id, *key))
            if key in identities and identities[key] != identifier:
                raise ValueError("Binding identity differs between operation and legacy projection")
            identities[key] = identifier
            binding["binding_id"] = identifier

    operations = result.get("operations")
    if operations is not None:
        for operation in operations:
            populate(operation["kind"], operation.get("bindings", []))
    kind = result.get("kind", operations[0]["kind"] if operations else "chat")
    populate(kind, result.get("bindings", []))
    return result


def upgrade() -> None:
    connection = op.get_bind()
    models = sa.table("llm_models", sa.column("id"), sa.column("configuration", sa.JSON()))
    for row in connection.execute(sa.select(models)).mappings():
        previous = row["configuration"]
        updated = backfill_configuration(row["id"], previous)
        if updated != previous:
            connection.execute(
                models.update().where(models.c.id == row["id"]).values(configuration=updated)
            )


def downgrade() -> None:
    raise RuntimeError("稳定绑定身份不可自动删除；无新流量时按已演练备份恢复，否则保留数据前滚修复")
