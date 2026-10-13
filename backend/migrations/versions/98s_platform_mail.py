"""Optional encrypted platform mail configuration; environment remains the fallback."""

import sqlalchemy as sa
from alembic import op

revision = "98s_platform_mail"
down_revision = "97r_platform_logo_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("installation", sa.Column("platform_mail_ciphertext", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("installation", "platform_mail_ciphertext")
