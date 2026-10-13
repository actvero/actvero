"""Explicit portal homepage policy, disabled by default.

Revision ID: 108c_site_portal
Revises: 107b_desktop_discovery
"""

import sqlalchemy as sa
from alembic import op

revision = "108c_site_portal"
down_revision = "107b_desktop_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "installation",
        sa.Column("portal_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("installation", "portal_enabled")
