"""Name-only personal keys inherit live member permissions; preserve existing scopes."""

import sqlalchemy as sa
from alembic import op

revision = "88i_member_access_keys"
down_revision = "87h_access_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "access_keys",
        sa.Column("scope_mode", sa.String(16), nullable=False, server_default="selected"),
    )
    op.alter_column(
        "access_keys", "expires_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )


def downgrade() -> None:
    # Explicitly refuse a lossy downgrade instead of silently broadening or invalidating keys.
    count = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM access_keys WHERE scope_mode <> 'selected' OR expires_at IS NULL"
        )
    )
    if count:
        raise RuntimeError("存在跟随成员权限或无到期时间的密钥，不能无损回退此迁移")
    op.alter_column(
        "access_keys", "expires_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
    op.drop_column("access_keys", "scope_mode")
