"""Model monetary reservations, settlement and member window clocks."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "86g_llm_settlement"
down_revision = "85f_llm_point_conversion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_settlements",
        sa.Column("id", sa.Uuid(), sa.ForeignKey("llm_calls.id"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(128)),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "conversion_id", sa.Uuid(), sa.ForeignKey("llm_point_conversions.id"), nullable=False
        ),
        sa.Column("ratio", sa.Numeric(25, 12), nullable=False),
        sa.Column("reserved_amount", sa.Numeric(60, 30), nullable=False),
        sa.Column("amount", sa.Numeric(60, 30)),
        sa.Column("price", postgresql.JSONB(), nullable=False),
        sa.Column("policy_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("usage", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("tenant_id", "member_id", "idempotency_key"),
        sa.CheckConstraint("reserved_amount >= 0 AND (amount IS NULL OR amount >= 0)"),
        sa.CheckConstraint("status IN ('reserved', 'review', 'settled', 'released')"),
    )
    for column in ("tenant_id", "member_id", "created_at"):
        op.create_index("ix_llm_settlements_" + column, "llm_settlements", [column])
    op.create_table(
        "llm_quota_clocks",
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("windows", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_llm_quota_clocks_tenant_id", "llm_quota_clocks", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("llm_quota_clocks")
    op.drop_table("llm_settlements")
