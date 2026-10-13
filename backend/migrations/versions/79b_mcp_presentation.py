"""Connector presentation metadata; existing services and credentials are preserved."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "79b_mcp_presentation"
down_revision = "79a_mcp_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, type_, default in (
        ("display_name", sa.String(100), ""),
        ("icon", sa.Text(), ""),
        ("examples", postgresql.JSONB(), "[]"),
    ):
        op.add_column(
            "mcp_services", sa.Column(name, type_, nullable=False, server_default=default)
        )
        op.alter_column("mcp_services", name, server_default=None)


def downgrade() -> None:
    for name in ("examples", "icon", "display_name"):
        op.drop_column("mcp_services", name)
