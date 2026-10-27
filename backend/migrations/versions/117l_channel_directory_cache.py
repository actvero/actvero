"""Preserve completeness metadata alongside the persisted upstream directory."""

import sqlalchemy as sa
from alembic import op

revision = "117l_channel_directory_cache"
down_revision = "116k_model_timeouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep existing lists and timestamps. Their completeness is unknown.
    op.add_column("model_channels", sa.Column("snapshot_partial", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_channels", "snapshot_partial")
