"""Organization opening policy, invitation recipients and reviewed applications."""

import sqlalchemy as sa
from alembic import op

revision = "99t_organization_onboarding"
down_revision = "98s_platform_mail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "installation",
        sa.Column("registration_mode", sa.String(20), nullable=False, server_default="invite"),
    )
    op.add_column(
        "installation",
        sa.Column(
            "invitation_verify_email", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_check_constraint(
        "ck_registration_mode",
        "installation",
        "registration_mode IN ('invite', 'approval', 'self_service')",
    )
    op.add_column("organization_invitations", sa.Column("recipient_email", sa.String(320)))
    op.create_table(
        "organization_openings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("invitation_id", sa.Uuid(), sa.ForeignKey("organization_invitations.id")),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("organization_name", sa.String(60), nullable=False),
        sa.Column("email", sa.String(320)),
        sa.Column("subject", sa.String(255)),
        sa.Column("registration_marker", sa.String(64)),
        sa.Column("applicant_id", sa.Uuid(), sa.ForeignKey("users.id"), index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("tenants.id")),
        sa.Column("reviewed_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('draft', 'pending', 'approved', 'rejected', 'completed')",
            name="ck_opening_status",
        ),
        sa.CheckConstraint(
            "mode IN ('invite', 'approval', 'self_service')", name="ck_opening_mode"
        ),
    )
    op.add_column(
        "web_sessions",
        sa.Column("organization_opening_id", sa.Uuid(), sa.ForeignKey("organization_openings.id")),
    )


def downgrade() -> None:
    op.drop_column("web_sessions", "organization_opening_id")
    op.drop_table("organization_openings")
    op.drop_column("organization_invitations", "recipient_email")
    op.drop_constraint("ck_registration_mode", "installation", type_="check")
    op.drop_column("installation", "invitation_verify_email")
    op.drop_column("installation", "registration_mode")
