"""Single organization and administrator registration for the community edition.

Refuses databases containing multiple organizations; never deletes existing data.
"""

import sqlalchemy as sa
from alembic import op

revision = "73a_single_organization"
down_revision = "6d0588b81a3a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    count = op.get_bind().scalar(sa.text("SELECT count(*) FROM tenants"))
    if count and count > 1:
        raise RuntimeError("社区版只支持一个组织；请使用独立数据库，不自动合并或删除已有组织")
    op.add_column(
        "tenants", sa.Column("instance_slot", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_check_constraint("ck_single_organization_slot", "tenants", "instance_slot = 1")
    op.create_unique_constraint("uq_single_organization", "tenants", ["instance_slot"])
    op.add_column("installation", sa.Column("organization_name", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("installation", "organization_name")
    op.drop_constraint("uq_single_organization", "tenants", type_="unique")
    op.drop_constraint("ck_single_organization_slot", "tenants", type_="check")
    op.drop_column("tenants", "instance_slot")
