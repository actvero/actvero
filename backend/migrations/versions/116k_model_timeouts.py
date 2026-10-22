"""Replace legacy default execution cutoffs with explicit progress timeouts."""

from copy import deepcopy
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "116k_model_timeouts"
down_revision = "115j_cli_consent"
branch_labels = None
depends_on = None

# Frozen defaults: migration behavior must not follow future runtime changes.
DEFAULTS = {
    "connect_timeout_seconds": 10,
    "first_response_timeout_seconds": 180,
    "stream_idle_timeout_seconds": 180,
}


def backfill(configuration: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(configuration)
    for part in [result, *(result.get("operations") or [])]:
        if "routing" not in part and "kind" not in part:
            continue  # Do not normalize unrelated legacy metadata-only records.
        policy = part.setdefault("routing", {})
        legacy = not any(key in policy for key in DEFAULTS)
        if legacy and policy.get("total_timeout_seconds", 60) == 60:
            policy["total_timeout_seconds"] = 1800
        for key, value in DEFAULTS.items():
            policy.setdefault(key, value)
    return result


def upgrade() -> None:
    connection = op.get_bind()
    models = sa.table(
        "llm_models", sa.column("id"), sa.column("configuration", sa.JSON()), sa.column("version")
    )
    for row in connection.execute(sa.select(models)).mappings():
        previous = row["configuration"]
        updated = backfill(previous)
        if updated != previous:
            connection.execute(
                models.update()
                .where(models.c.id == row["id"])
                .values(configuration=updated, version=models.c.version + 1)
            )


def downgrade() -> None:
    # Older servers reject extended limits. Do not silently shorten live policy.
    connection = op.get_bind()
    models = sa.table("llm_models", sa.column("id"), sa.column("configuration", sa.JSON()))
    rows = list(connection.execute(sa.select(models)).mappings())
    for row in rows:
        parts = [row["configuration"], *(row["configuration"].get("operations") or [])]
        if any(part.get("routing", {}).get("total_timeout_seconds", 60) > 180 for part in parts):
            raise RuntimeError("旧版本不支持当前模型总时限；请先显式调整配置或使用已验证的备份恢复")
    for row in rows:
        updated = deepcopy(row["configuration"])
        for part in [updated, *(updated.get("operations") or [])]:
            for key in DEFAULTS:
                part.get("routing", {}).pop(key, None)
        connection.execute(
            models.update().where(models.c.id == row["id"]).values(configuration=updated)
        )
