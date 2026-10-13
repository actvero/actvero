"""Explicit device policy, workspace selection and confirmed refresh recovery.

Revision ID: 104y_device_session_policy
Revises: 103x_web_session_policy
"""

import sqlalchemy as sa
from alembic import op

revision = "104y_device_session_policy"
down_revision = "103x_web_session_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_sessions",
        sa.Column("policy_mode", sa.String(20), nullable=False, server_default="strict"),
    )
    op.add_column("device_sessions", sa.Column("absolute_expires_at", sa.DateTime(timezone=True)))
    op.add_column("device_sessions", sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id")))
    op.add_column("device_tokens", sa.Column("acknowledged_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE device_sessions SET absolute_expires_at=expires_at")
    op.create_check_constraint(
        "device_session_policy_mode", "device_sessions", "policy_mode IN ('strict', 'persistent')"
    )


def downgrade() -> None:
    op.drop_constraint("device_session_policy_mode", "device_sessions", type_="check")
    op.drop_column("device_tokens", "acknowledged_at")
    for column in ("tenant_id", "absolute_expires_at", "policy_mode"):
        op.drop_column("device_sessions", column)
