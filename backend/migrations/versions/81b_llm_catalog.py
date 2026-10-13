"""model configuration and draft prices

Revision ID: 81b_llm_catalog
Revises: 80a_model_channels
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "81b_llm_catalog"
down_revision = "80a_model_channels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug"),
    )
    op.create_index("ix_llm_models_tenant_id", "llm_models", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_models_tenant_id", table_name="llm_models")
    op.drop_table("llm_models")
