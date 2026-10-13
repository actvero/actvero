"""Device-bound MCP resource tokens and native personal OAuth; additive only."""

import sqlalchemy as sa
from alembic import op

revision = "79e_desktop_mcp"
down_revision = "79d_mcp_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "desktop_resource_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("device_sessions.id"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    for key in ("device_id", "expires_at"):
        op.create_index("ix_desktop_resource_tokens_" + key, "desktop_resource_tokens", [key])
    op.create_table(
        "desktop_mcp_oauth_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("device_id", sa.Uuid(), sa.ForeignKey("device_sessions.id"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column(
            "service_id",
            sa.Uuid(),
            sa.ForeignKey("mcp_services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("verifier", sa.Text(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("pending_tokens", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_desktop_mcp_oauth_attempts_device_id", "desktop_mcp_oauth_attempts", ["device_id"]
    )
    op.add_column("mcp_activities", sa.Column("device_session_id", sa.Uuid(), nullable=True))
    op.add_column(
        "mcp_activities",
        sa.Column("client_version", sa.String(50), nullable=False, server_default=""),
    )
    op.alter_column("mcp_activities", "client_version", server_default=None)


def downgrade() -> None:
    op.drop_column("mcp_activities", "client_version")
    op.drop_column("mcp_activities", "device_session_id")
    op.drop_table("desktop_mcp_oauth_attempts")
    op.drop_table("desktop_resource_tokens")
