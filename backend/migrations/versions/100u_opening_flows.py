"""Isolate organization opening contexts without replacing existing sessions or drafts."""

import sqlalchemy as sa
from alembic import op

revision = "100u_opening_flows"
down_revision = "99t_organization_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organization_opening_flows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("web_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("invitation_id", sa.Uuid(), sa.ForeignKey("organization_invitations.id")),
        sa.Column("invitation_hash", sa.String(64)),
        sa.Column("opening_id", sa.Uuid(), sa.ForeignKey("organization_openings.id")),
        sa.Column("organization_name", sa.String(60), nullable=False, server_default=""),
        sa.Column("login_state", sa.String(64), index=True),
        sa.Column("login_expires_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("organization_opening_flows")
