"""Allow explicit channel diagnostics without inventing a public model identity."""

import sqlalchemy as sa
from alembic import op

revision = "95p_diagnostic_calls"
down_revision = "94o_channel_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("llm_calls", "model_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        "ck_llm_call_model_source",
        "llm_calls",
        "(source = 'channel_diagnostic' AND model_id IS NULL) OR "
        "(source <> 'channel_diagnostic' AND model_id IS NOT NULL)",
    )
    # Historical JSON attempts and channel audit records stay byte-for-byte intact.
    # Missing send/termination/usage evidence must not be backfilled as known facts.


def downgrade() -> None:
    raise RuntimeError(
        "渠道诊断记录不能自动删除或伪造模型身份；停止流量后恢复已演练备份或保留数据前滚修复"
    )
