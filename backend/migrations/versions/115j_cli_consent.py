"""Bind new CLI grants to browser-approved identity, scope and organizations."""

import sqlalchemy as sa
from alembic import op

revision = "115j_cli_consent"
down_revision = "114i_cli_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("management_sessions", sa.Column("authorized_org_ids", sa.JSON(), nullable=True))
    op.add_column(
        "management_logins",
        sa.Column("authorization_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "management_logins",
        sa.Column("reauthenticate", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "management_logins",
        sa.Column("approved_identity_id", sa.Uuid(), sa.ForeignKey("login_identities.id")),
    )
    op.add_column("management_logins", sa.Column("authorized_org_ids", sa.JSON(), nullable=True))
    op.add_column("management_logins", sa.Column("approved_at", sa.DateTime(timezone=True)))
    # Historical write sessions have no browser approval. Read-only sessions remain usable.
    op.execute(
        "UPDATE management_sessions SET revoked_at = CURRENT_TIMESTAMP "
        "WHERE scope LIKE '%management:write%' AND revoked_at IS NULL"
    )


def downgrade() -> None:
    # Older servers cannot enforce organization-bound grants.
    op.execute(
        "UPDATE management_sessions SET revoked_at = CURRENT_TIMESTAMP "
        "WHERE authorized_org_ids::text <> 'null' AND revoked_at IS NULL"
    )
    for name in (
        "approved_at",
        "authorized_org_ids",
        "approved_identity_id",
        "reauthenticate",
        "authorization_version",
    ):
        op.drop_column("management_logins", name)
    op.drop_column("management_sessions", "authorized_org_ids")
