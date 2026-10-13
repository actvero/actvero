"""bind capability approval to discovered contract

Revision ID: 79a_mcp_contract
Revises: 78f_mcp_workbench
"""

import sqlalchemy as sa
from alembic import op

revision = "79a_mcp_contract"
down_revision = "78f_mcp_workbench"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_capability_policies",
        sa.Column("definition_hash", sa.String(length=64), nullable=False, server_default=""),
    )

    op.alter_column("mcp_capability_policies", "definition_hash", server_default=None)


def downgrade() -> None:
    op.drop_column("mcp_capability_policies", "definition_hash")
