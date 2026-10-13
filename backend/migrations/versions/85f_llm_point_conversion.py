"""Versioned model point conversion; no default currency or conversion ratio."""

import sqlalchemy as sa
from alembic import op

revision = "85f_llm_point_conversion"
down_revision = "84e_quota_policies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_point_conversions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("points_per_currency", sa.Numeric(25, 12), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "version"),
        sa.CheckConstraint("points_per_currency > 0 AND points_per_currency <= 1000000000000"),
        sa.CheckConstraint("version >= 1"),
    )
    op.create_index("ix_llm_point_conversions_tenant_id", "llm_point_conversions", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("llm_point_conversions")
