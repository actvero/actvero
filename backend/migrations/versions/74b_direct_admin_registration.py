"""Retire the installation code; preserve in-progress registration correlation.

Existing accounts, organizations and sessions are left intact. The old expiry and
browser setup hash columns remain unused for a data-preserving migration.
"""

from alembic import op

revision = "74b_direct_admin_registration"
down_revision = "73a_single_organization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("installation", "grant_hash", new_column_name="registration_marker")


def downgrade() -> None:
    op.alter_column("installation", "registration_marker", new_column_name="grant_hash")
