"""Shared route health and logical-request attempt history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "83d_llm_routing"
down_revision = "82c_llm_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_calls", sa.Column("termination_code", sa.String(60), nullable=True))
    op.add_column(
        "llm_calls", sa.Column("attempts", postgresql.JSONB(), nullable=False, server_default="[]")
    )
    op.alter_column("llm_calls", "attempts", server_default=None)
    op.create_table(
        "llm_route_health",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("probe_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_llm_route_health_tenant_id", "llm_route_health", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("llm_route_health")
    op.drop_column("llm_calls", "attempts")
    op.drop_column("llm_calls", "termination_code")
