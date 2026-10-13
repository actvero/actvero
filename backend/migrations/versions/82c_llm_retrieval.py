"""Retrieval invocation metadata. Existing model JSON gains backward-compatible defaults."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "82c_llm_retrieval"
down_revision = "81b_llm_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("model_id", sa.Uuid(), sa.ForeignKey("llm_models.id"), nullable=False),
        sa.Column("channel_id", sa.Uuid(), sa.ForeignKey("model_channels.id"), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("device_sessions.id"), nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("usage", postgresql.JSONB(), nullable=False),
        sa.Column("prices", postgresql.JSONB(), nullable=False),
        sa.Column("estimates", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_calls_tenant_id", "llm_calls", ["tenant_id"])
    op.create_index("ix_llm_calls_model_id", "llm_calls", ["model_id"])


def downgrade() -> None:
    op.drop_table("llm_calls")
