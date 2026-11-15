"""Allow organization knowledge settlements without personal point accounting."""

import sqlalchemy as sa
from alembic import op

revision = "129u_knowledge_org_usage"
down_revision = "128t_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column in ("member_id", "conversion_id", "ratio"):
        op.alter_column("llm_settlements", column, nullable=True)
    op.create_check_constraint(
        "ck_llm_settlement_quota_subject",
        "llm_settlements",
        "(member_id IS NOT NULL AND conversion_id IS NOT NULL AND ratio IS NOT NULL) OR "
        "(member_id IS NULL AND conversion_id IS NULL AND ratio IS NULL "
        "AND idempotency_key IS NULL AND request_fingerprint IS NULL)",
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM llm_settlements WHERE member_id IS NULL)")
    ):
        raise RuntimeError("Organization settlements cannot be represented by the older schema")
    op.drop_constraint("ck_llm_settlement_quota_subject", "llm_settlements", type_="check")
    for column in ("member_id", "conversion_id", "ratio"):
        op.alter_column("llm_settlements", column, nullable=False)
