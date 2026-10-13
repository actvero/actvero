"""MCP per-service connection options, activity records and identity-scoped health."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "79d_mcp_operations"
down_revision = "79c_mcp_initial_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_services",
        sa.Column("connection_options", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.alter_column("mcp_services", "connection_options", server_default=None)
    op.create_table(
        "mcp_health",
        sa.Column(
            "service_id",
            sa.Uuid(),
            sa.ForeignKey("mcp_services.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("owner_id", sa.Uuid(), primary_key=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("failures", sa.Integer(), nullable=False),
    )
    op.create_table(
        "mcp_activities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("service_name", sa.String(100), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_name", sa.String(200), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("capability", sa.String(2000), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(40), nullable=False),
        sa.Column("message", sa.String(200), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("tenant_id", "service_id", "category", "created_at"):
        op.create_index("ix_mcp_activities_" + column, "mcp_activities", [column])


def downgrade() -> None:
    op.drop_table("mcp_activities")
    op.drop_table("mcp_health")
    op.drop_column("mcp_services", "connection_options")
