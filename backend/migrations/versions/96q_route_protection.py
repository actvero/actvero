"""Keep rejection scope and serialize outcomes without rewriting prior health."""

import sqlalchemy as sa
from alembic import op

revision = "96q_route_protection"
down_revision = "95p_diagnostic_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_route_health", sa.Column("block_reason", sa.String(32), nullable=True))
    op.add_column(
        "llm_route_health",
        sa.Column("health_generation", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_llm_route_block_reason",
        "llm_route_health",
        "block_reason IS NULL OR block_reason IN ('model_unavailable', 'unclassified_rejection')",
    )
    op.create_check_constraint(
        "ck_llm_route_generation", "llm_route_health", "health_generation >= 0"
    )


def downgrade() -> None:
    raise RuntimeError("路由保护状态不能自动丢弃；停止流量后恢复备份或保留数据前滚修复")
