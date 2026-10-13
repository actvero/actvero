"""Remember first administrator discovery without changing existing capability choices."""

import sqlalchemy as sa
from alembic import op

revision = "79c_mcp_initial_catalog"
down_revision = "79b_mcp_presentation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mcp_services",
        sa.Column("catalog_initialized", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("""UPDATE mcp_services SET catalog_initialized = true
        WHERE EXISTS (SELECT 1 FROM mcp_snapshots s
            WHERE s.service_id = mcp_services.id AND s.checked_at IS NOT NULL)
        OR EXISTS (SELECT 1 FROM mcp_capability_policies p WHERE p.service_id = mcp_services.id)""")
    op.alter_column("mcp_services", "catalog_initialized", server_default=None)


def downgrade() -> None:
    op.drop_column("mcp_services", "catalog_initialized")
