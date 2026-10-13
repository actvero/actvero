"""Personal display profile and explicit logout state; preserve existing identities."""

import sqlalchemy as sa
from alembic import op

revision = "75c_account_profile"
down_revision = "74b_direct_admin_registration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("name_managed_locally", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("users", sa.Column("avatar_data", sa.LargeBinary(), nullable=True))
    op.add_column("users", sa.Column("avatar_version", sa.Uuid(), nullable=True))
    op.add_column(
        "web_sessions",
        sa.Column("requires_reauth", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("web_sessions", "requires_reauth")
    op.drop_column("users", "avatar_version")
    op.drop_column("users", "avatar_data")
    op.drop_column("users", "name_managed_locally")
