"""mcp workbench and isolated connections

Revision ID: 78f_mcp_workbench
Revises: 77e_desktop_sessions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "78f_mcp_workbench"
down_revision = "77e_desktop_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_services",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("transport", sa.String(length=20), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("audience", sa.String(length=20), nullable=False),
        sa.Column("member_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("auth_mode", sa.String(length=20), nullable=False),
        sa.Column("credential_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("oauth", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    op.create_index(op.f("ix_mcp_services_tenant_id"), "mcp_services", ["tenant_id"], unique=False)
    op.create_table(
        "mcp_capability_policies",
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("key", sa.String(length=2000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["service_id"], ["mcp_services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("service_id", "kind", "key"),
    )
    op.create_table(
        "mcp_connections",
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("sealed", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["mcp_services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("service_id", "owner_id"),
    )
    op.create_table(
        "mcp_contents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("arguments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["mcp_services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_id", "kind", "name"),
    )
    op.create_index(
        op.f("ix_mcp_contents_service_id"), "mcp_contents", ["service_id"], unique=False
    )
    op.create_table(
        "mcp_snapshots",
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("protocol", sa.String(length=100), nullable=False),
        sa.Column("negotiated", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["service_id"], ["mcp_services.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("service_id", "owner_id"),
    )
    op.create_table(
        "mcp_oauth_attempts",
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("member_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("verifier", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["memberships.id"],
        ),
        sa.ForeignKeyConstraint(["service_id"], ["mcp_services.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["web_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("state_hash"),
    )


def downgrade() -> None:
    op.drop_table("mcp_oauth_attempts")
    op.drop_table("mcp_snapshots")
    op.drop_index(op.f("ix_mcp_contents_service_id"), table_name="mcp_contents")
    op.drop_table("mcp_contents")
    op.drop_table("mcp_connections")
    op.drop_table("mcp_capability_policies")
    op.drop_index(op.f("ix_mcp_services_tenant_id"), table_name="mcp_services")
    op.drop_table("mcp_services")
