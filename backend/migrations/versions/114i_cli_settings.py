"""Persist the platform CLI access choice while preserving deployment defaults."""

import sqlalchemy as sa
from alembic import op

revision = "114i_cli_settings"
down_revision = "113h_management_merge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("installation", sa.Column("management_enabled", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("installation", "management_enabled")
