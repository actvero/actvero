"""Add SaaS workspace state while preserving the community edition guard.

Set ``ACTVERO_PLATFORM_EDITION=saas`` when upgrading a SaaS database. The
single-organization constraints are removed only in that explicit mode.
"""

import os

import sqlalchemy as sa
from alembic import op

revision = "93n_platform_operators"
down_revision = "92m_merge_skills_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if os.getenv("ACTVERO_PLATFORM_EDITION", "community") == "saas":
        op.drop_constraint("uq_single_organization", "tenants", type_="unique")
        op.drop_constraint("ck_single_organization_slot", "tenants", type_="check")
    op.add_column("installation", sa.Column("platform_operator_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_installation_platform_operator_user",
        "installation",
        "users",
        ["platform_operator_user_id"],
        ["id"],
    )
    op.add_column("web_sessions", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_web_sessions_tenant", "web_sessions", "tenants", ["tenant_id"], ["id"]
    )
    op.add_column(
        "invitations",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
    )
    op.create_check_constraint(
        "ck_invitation_role", "invitations", "role IN ('administrator', 'member')"
    )
    op.create_table(
        "platform_operators",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('active', 'paused')"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("platform_operators")
    op.drop_constraint("ck_invitation_role", "invitations", type_="check")
    op.drop_column("invitations", "role")
    op.drop_constraint("fk_web_sessions_tenant", "web_sessions", type_="foreignkey")
    op.drop_column("web_sessions", "tenant_id")
    op.drop_constraint("fk_installation_platform_operator_user", "installation", type_="foreignkey")
    op.drop_column("installation", "platform_operator_user_id")
    if os.getenv("ACTVERO_PLATFORM_EDITION", "community") == "saas":
        op.create_check_constraint("ck_single_organization_slot", "tenants", "instance_slot = 1")
        op.create_unique_constraint("uq_single_organization", "tenants", ["instance_slot"])
