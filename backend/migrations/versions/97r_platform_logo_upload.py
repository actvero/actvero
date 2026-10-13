"""Persist an optional normalized platform logo for the shared brand."""

import sqlalchemy as sa
from alembic import op

revision = "97r_platform_logo_upload"
down_revision = "96q_platform_branding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("installation", sa.Column("platform_logo_data", sa.LargeBinary(), nullable=True))
    op.add_column("installation", sa.Column("platform_logo_version", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("installation", "platform_logo_version")
    op.drop_column("installation", "platform_logo_data")
