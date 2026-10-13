"""Durable administrator-created member correlation without credentials."""

import sqlalchemy as sa
from alembic import op

revision = "76d_direct_members"
down_revision = "75c_account_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "member_creations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("marker", sa.String(64), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("tenant_id", "email"),
        sa.CheckConstraint("role IN ('administrator', 'member')"),
    )


def downgrade() -> None:
    op.drop_table("member_creations")
