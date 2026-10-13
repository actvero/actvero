"""Independent quota policy configuration; no consumption or monetary defaults."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "84e_quota_policies"
down_revision = "83d_llm_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_policies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("member_ids", postgresql.JSONB(), nullable=False),
        sa.Column("rules", postgresql.JSONB(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("priority >= 0 AND priority <= 1000000"),
        sa.CheckConstraint("priority <> 0 OR NOT archived"),
    )
    op.create_index("ix_quota_policies_tenant_id", "quota_policies", ["tenant_id"])
    for name, field in [("uq_quota_priority", "priority"), ("uq_quota_name", "name")]:
        op.create_index(
            name,
            "quota_policies",
            ["tenant_id", field],
            unique=True,
            postgresql_where=sa.text("NOT archived"),
        )


def downgrade() -> None:
    op.drop_table("quota_policies")
