"""Store optional SaaS platform branding without changing fresh defaults."""

import sqlalchemy as sa
from alembic import op

revision = "96q_platform_branding"
down_revision = "95p_org_invitation_copy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("installation", sa.Column("platform_name", sa.String(length=80), nullable=True))
    op.add_column(
        "installation", sa.Column("platform_logo_url", sa.String(length=2048), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("installation", "platform_logo_url")
    op.drop_column("installation", "platform_name")
