"""Session-bound MCP OAuth for the independent management client."""

import sqlalchemy as sa
from alembic import op

revision = "112g_management_mcp_oauth"
down_revision = "111f_management_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "management_mcp_oauth_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("management_sessions.id"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column(
            "service_id",
            sa.Uuid(),
            sa.ForeignKey("mcp_services.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("verifier", sa.Text()),
        sa.Column("authorization_url", sa.Text()),
        sa.Column("pending_tokens", sa.Text()),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("error_code", sa.String(60)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_management_mcp_oauth_attempts_session_id",
        "management_mcp_oauth_attempts",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_table("management_mcp_oauth_attempts")
