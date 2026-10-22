"""Explicit management write grants and organization-scoped command receipts."""

import sqlalchemy as sa
from alembic import op

revision = "111f_management_resources"
down_revision = "110e_client_downloads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "management_logins",
        sa.Column("scope", sa.String(100), nullable=False, server_default="management:read"),
    )
    op.create_table(
        "management_commands",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(250), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("management_commands")
    op.drop_column("management_logins", "scope")
