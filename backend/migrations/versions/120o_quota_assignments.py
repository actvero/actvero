"""Separate reusable quota policies from each member's effective assignment."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "120o_quota_assignments"
down_revision = "119n_fixed_quota_cycles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quota_policies",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "quota_policies", sa.Column("mode", sa.String(16), nullable=False, server_default="limited")
    )
    op.execute("UPDATE quota_policies SET is_default = (priority = 0)")
    op.create_table(
        "quota_assignments",
        sa.Column("member_id", sa.UUID(), sa.ForeignKey("memberships.id"), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("policy_id", sa.UUID(), sa.ForeignKey("quota_policies.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_quota_assignments_tenant_id", "quota_assignments", ["tenant_id"])
    op.create_index("ix_quota_assignments_policy_id", "quota_assignments", ["policy_id"])
    # Preserve the previously selected whole policy, including paused members.
    # Defaults stay inherited so later default-policy edits still apply.
    op.execute("""
        INSERT INTO quota_assignments (member_id, tenant_id, policy_id)
        SELECT DISTINCT ON (m.id) m.id, m.tenant_id, p.id
        FROM memberships m JOIN quota_policies p ON p.tenant_id = m.tenant_id
        WHERE NOT p.archived AND p.priority > 0
          AND p.member_ids @> jsonb_build_array(m.id::text)
        ORDER BY m.id, p.priority DESC
    """)
    op.drop_index("uq_quota_priority", table_name="quota_policies")
    op.drop_column("quota_policies", "priority")
    op.drop_column("quota_policies", "member_ids")
    op.create_index(
        "uq_quota_default",
        "quota_policies",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_default AND NOT archived"),
    )
    op.create_check_constraint(
        "ck_quota_mode", "quota_policies", "mode IN ('limited', 'unlimited')"
    )
    op.create_check_constraint(
        "ck_quota_mode_rules",
        "quota_policies",
        "(mode = 'unlimited' AND jsonb_array_length(rules) = 0) OR "
        "(mode = 'limited' AND jsonb_array_length(rules) > 0)",
    )
    op.create_check_constraint(
        "ck_quota_default_active", "quota_policies", "NOT is_default OR NOT archived"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM quota_policies WHERE mode = 'unlimited')")
    ):
        raise RuntimeError("Unlimited quota policies cannot be represented by the older schema")
    op.add_column(
        "quota_policies", sa.Column("priority", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "quota_policies", sa.Column("member_ids", JSONB(), nullable=False, server_default="[]")
    )
    op.execute("""
        WITH numbered AS (
          SELECT id, row_number() OVER (PARTITION BY tenant_id ORDER BY created_at, id) AS n
          FROM quota_policies WHERE NOT is_default
        ) UPDATE quota_policies p SET priority = n FROM numbered WHERE p.id = numbered.id
    """)
    op.execute("""
        UPDATE quota_policies p SET member_ids = assigned.members
        FROM (SELECT policy_id, jsonb_agg(member_id::text) AS members
              FROM quota_assignments WHERE policy_id IS NOT NULL GROUP BY policy_id) assigned
        WHERE p.id = assigned.policy_id
    """)
    op.drop_table("quota_assignments")
    op.drop_index("uq_quota_default", table_name="quota_policies")
    op.drop_column("quota_policies", "is_default")
    op.drop_column("quota_policies", "mode")
    op.create_index(
        "uq_quota_priority",
        "quota_policies",
        ["tenant_id", "priority"],
        unique=True,
        postgresql_where=sa.text("NOT archived"),
    )
    op.create_check_constraint(
        "ck_quota_priority_range", "quota_policies", "priority >= 0 AND priority <= 1000000"
    )
    op.create_check_constraint(
        "ck_quota_default_not_archived", "quota_policies", "priority <> 0 OR NOT archived"
    )
