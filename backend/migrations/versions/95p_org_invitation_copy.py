"""Keep pending organization invitation links available for authorized copying."""

import sqlalchemy as sa
from alembic import op

revision = "95p_org_invitation_copy"
down_revision = "94o_organization_invitations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organization_invitations", sa.Column("token_ciphertext", sa.String(1000), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("organization_invitations", "token_ciphertext")
