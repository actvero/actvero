"""Promote existing single-operation configurations without changing access or prices."""

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "90k_model_operations"
down_revision = "89j_key_secret_visibility"
branch_labels = None
depends_on = None

FIELDS = (
    "kind",
    "retrieval",
    "routing",
    "context_window",
    "max_output",
    "capabilities",
    "reasoning_options",
    "bindings",
    "budget_price",
)


def key(parts: list[object]) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def upgrade() -> None:
    connection = op.get_bind()
    models = sa.table(
        "llm_models", sa.column("id"), sa.column("tenant_id"), sa.column("configuration", sa.JSON())
    )
    health = sa.table("llm_route_health", sa.column("id"))
    for row in connection.execute(sa.select(models)).mappings():
        config = dict(row["configuration"])
        if config.get("operations") is not None:
            continue
        kind = config.get("kind", "chat")
        access = config.get("access", {})
        operation = {name: config[name] for name in FIELDS if name in config}
        operation.update(
            kind=kind,
            enabled=True,
            channel_id=access.get("channel_id"),
            upstream_id=access.get("upstream_id", ""),
        )
        # Legacy binding defaults were enabled. Make that explicit before new defaults apply.
        operation["bindings"] = [
            dict(binding, enabled=binding.get("enabled", True))
            for binding in config.get("bindings", [])
        ]
        config["operations"] = [operation]
        connection.execute(
            models.update().where(models.c.id == row["id"]).values(configuration=config)
        )
        for binding in operation["bindings"]:
            prefix = [str(row["tenant_id"]), str(row["id"])]
            suffix = [binding["channel_id"], binding["upstream_id"]]
            connection.execute(
                health.update()
                .where(health.c.id == key(prefix + suffix))
                .values(id=key(prefix + [kind] + suffix))
            )


def downgrade() -> None:
    # Multi-operation data cannot be represented losslessly in the old runtime.
    raise RuntimeError("多操作模型迁移不可自动回退；请恢复升级前备份")
