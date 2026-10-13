"""Encrypted owner reveal and logical deletion preserving usage references."""

import sqlalchemy as sa
from alembic import op

revision = "89j_key_secret_visibility"
down_revision = "88i_member_access_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("access_keys", sa.Column("sealed_secret", sa.Text(), nullable=True))
    op.add_column("access_keys", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM access_keys "
            "WHERE sealed_secret IS NOT NULL OR deleted_at IS NOT NULL"
        )
    ):
        raise RuntimeError("存在可查看或已删除密钥，不能无损回退")
    op.drop_column("access_keys", "deleted_at")
    op.drop_column("access_keys", "sealed_secret")
