"""Join the retained gateway, organization and expert migration histories.

All parent revisions are preserved verbatim. The routing JSONB column is kept
as historical data; it does not enable name-based routing in the current runtime.
"""

revision = "101v_repository_consolidation"
down_revision = (
    "97r_settlement_evidence",
    "100u_opening_flows",
    "95p_merge_experts_routing",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    raise RuntimeError("整合后的多业务历史不能自动拆回；请按已演练的备份恢复或前滚修复")
