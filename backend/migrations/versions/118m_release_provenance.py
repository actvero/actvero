"""Persist shared release source identity without changing existing storage locators."""

import sqlalchemy as sa
from alembic import op

revision = "118m_release_provenance"
down_revision = "117l_client_distribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_storage",
        sa.Column("locator_frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE client_storage SET locator_frozen = true WHERE EXISTS "
        "(SELECT 1 FROM client_artifacts a WHERE a.storage_id = client_storage.id)"
    )
    op.alter_column("client_storage", "locator_frozen", server_default=None)
    op.add_column("client_distributions", sa.Column("source_commit", sa.String(40), nullable=True))


def downgrade() -> None:
    op.drop_column("client_storage", "locator_frozen")
    op.drop_column("client_distributions", "source_commit")
