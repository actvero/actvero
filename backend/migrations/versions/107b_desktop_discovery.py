"""Stable deployment identity and complete brand revision.

Revision ID: 107b_desktop_discovery
Revises: 106a_dependency_commands
"""

import sqlalchemy as sa
from alembic import op

revision = "107b_desktop_discovery"
down_revision = "106a_dependency_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("instance_id", "branding_revision"):
        op.add_column(
            "installation",
            sa.Column(name, sa.Uuid(), nullable=False, server_default=sa.text("gen_random_uuid()")),
        )


def downgrade() -> None:
    op.drop_column("installation", "branding_revision")
    op.drop_column("installation", "instance_id")
