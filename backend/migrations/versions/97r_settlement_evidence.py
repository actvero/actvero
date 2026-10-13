"""Keep member request identity and versioned automatic settlement evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "97r_settlement_evidence"
down_revision = "96q_route_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_settlements", sa.Column("request_fingerprint", sa.String(67), nullable=True))
    op.add_column(
        "llm_settlements",
        sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
    )
    # Old digests and usage provenance cannot be invented from historical records.


def downgrade() -> None:
    raise RuntimeError("请求幂等与结算证据不能自动丢弃；停止流量后恢复备份或前滚修复")
