"""Scoped atomic dependency update receipts.
Revision ID: 106a_dependency_commands
Revises: 105z_resource_adoptions
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "106a_dependency_commands"
down_revision = "105z_resource_adoptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dependency_command_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("updated_experts", JSONB(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("member_id", "request_id"),
    )
    for col in ("tenant_id", "member_id"):
        op.create_index(
            "ix_dependency_command_receipts_" + col, "dependency_command_receipts", [col]
        )


def downgrade() -> None:
    op.drop_table("dependency_command_receipts")
