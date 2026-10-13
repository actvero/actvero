"""Explicit adoption proofs and audited replacement of old Skill versions.

Revision ID: 105z_resource_adoptions
Revises: 104y_device_session_policy
"""

import sqlalchemy as sa
from alembic import op

revision = "105z_resource_adoptions"
down_revision = "104y_device_session_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_adoptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "device_session_id", sa.Uuid(), sa.ForeignKey("device_sessions.id"), nullable=False
        ),
        sa.Column("expert_id", sa.Uuid()),
        sa.Column("expert_release_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("member_id", "request_id"),
        sa.CheckConstraint("kind IN ('skills', 'experts')", name="resource_adoption_kind"),
    )
    for column in ("tenant_id", "member_id", "resource_id", "version_id"):
        op.create_index("ix_resource_adoptions_" + column, "resource_adoptions", [column])
    # Only known replacement audit records qualify. Missing/ambiguous/explicitly
    # withdrawn history stays unavailable; immutable ZIP/content/sha never changes.
    op.execute("""
        UPDATE skill_versions v SET status='superseded'
        FROM skills s
        WHERE v.skill_id=s.id AND v.status='withdrawn'
          AND v.id IS DISTINCT FROM s.default_version_id
          AND EXISTS (
            SELECT 1 FROM audit_events a
            WHERE a.tenant_id=s.tenant_id AND a.target_id=s.id
              AND a.action='skills.withdraw' AND a.result='success'
              AND a.details->>'version'=v.version AND a.details->>'replaced_by' IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM audit_events b
                WHERE b.tenant_id=s.tenant_id AND b.target_id=s.id
                  AND b.action='skills.withdraw' AND b.result='success'
                  AND b.details->>'version'=v.version AND b.details->>'replaced_by' IS NULL
                  AND b.created_at >= a.created_at
              )
          )
    """)


def downgrade() -> None:
    op.execute("UPDATE skill_versions SET status='withdrawn' WHERE status='superseded'")
    op.drop_table("resource_adoptions")
