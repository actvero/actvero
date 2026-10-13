"""custom model channels

Revision ID: 80a_model_channels
Revises: 79e_desktop_mcp
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "80a_model_channels"
down_revision = "79e_desktop_mcp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_channels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon", sa.Text(), nullable=False),
        sa.Column("base_url", sa.String(length=2000), nullable=False),
        sa.Column("auth_mode", sa.String(length=20), nullable=False),
        sa.Column("sealed_key", sa.Text(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("declared_apis", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("models", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    op.create_index(
        op.f("ix_model_channels_tenant_id"), "model_channels", ["tenant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_model_channels_tenant_id"), table_name="model_channels")
    op.drop_table("model_channels")
