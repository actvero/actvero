"""Cache New API upstream discovery independently of native channel configuration."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "118m_newapi_gateway"
down_revision = "117l_channel_directory_cache"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "newapi_model_directories",
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("channel_id", sa.Integer(), primary_key=True),
        sa.Column("connection_id", sa.String(64), nullable=False),
        sa.Column("models", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel_snapshot", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("newapi_model_directories")
