"""Add explicit Web session policy without extending or reviving existing sessions.

Revision ID: 103x_web_session_policy
Revises: 102w_freeze_legacy_routes
"""

import sqlalchemy as sa
from alembic import op

revision = "103x_web_session_policy"
down_revision = "102w_freeze_legacy_routes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "web_sessions",
        sa.Column("policy_mode", sa.String(20), nullable=False, server_default="strict"),
    )
    op.add_column("web_sessions", sa.Column("absolute_expires_at", sa.DateTime(timezone=True)))
    op.add_column("web_sessions", sa.Column("renewed_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE web_sessions SET absolute_expires_at = expires_at WHERE identity_id IS NOT NULL"
    )
    op.create_check_constraint(
        "web_session_policy_mode", "web_sessions", "policy_mode IN ('strict', 'persistent')"
    )


def downgrade() -> None:
    op.drop_constraint("web_session_policy_mode", "web_sessions", type_="check")
    for column in ("renewed_at", "absolute_expires_at", "policy_mode"):
        op.drop_column("web_sessions", column)
