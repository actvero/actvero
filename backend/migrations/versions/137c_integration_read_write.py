"""Separate application model invocation and knowledge mutations from read grants."""

import sqlalchemy as sa
from alembic import op

revision = "137c_integration_read_write"
down_revision = "136b_integration_resource_writes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for field in ("models", "knowledge"):
        op.add_column(
            "integration_applications",
            sa.Column(
                f"{field}_write_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
        op.execute(f"UPDATE integration_applications SET {field}_write_enabled = {field}_enabled")


def downgrade() -> None:
    for field in ("knowledge", "models"):
        op.execute(
            f"UPDATE integration_applications SET {field}_enabled = "
            f"{field}_enabled AND {field}_write_enabled"
        )
        op.drop_column("integration_applications", f"{field}_write_enabled")
