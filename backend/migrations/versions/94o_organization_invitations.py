"""Add one-time SaaS organization initialization invitations."""

import sqlalchemy as sa
from alembic import op

revision = "94o_organization_invitations"
down_revision = "93n_platform_operators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=True),
        sa.Column("organization_name", sa.String(length=60), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("needs_activation", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')",
            name="ck_organization_invitation_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["accepted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.add_column(
        "web_sessions",
        sa.Column("organization_invitation_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_web_sessions_organization_invitation",
        "web_sessions",
        "organization_invitations",
        ["organization_invitation_id"],
        ["id"],
    )
    op.add_column(
        "web_sessions",
        sa.Column("organization_invitation_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_web_sessions_organization_invitation", "web_sessions", type_="foreignkey"
    )
    op.drop_column("web_sessions", "organization_invitation_hash")
    op.drop_column("web_sessions", "organization_invitation_id")
    op.drop_table("organization_invitations")
