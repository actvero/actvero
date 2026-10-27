"""Allow installer publication without advancing automatic update channels."""

import sqlalchemy as sa
from alembic import op

revision = "119n_download_only_releases"
down_revision = "118m_release_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_distributions",
        sa.Column("updates_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("client_distributions", "updates_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("client_distributions", "updates_enabled")
