"""Store the optional catalog icon for each workbench version."""

import sqlalchemy as sa
from alembic import op

revision = "125r_workbench_version_icon"
down_revision = "124r_workbenches_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workbench_versions", sa.Column("icon_data_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workbench_versions", "icon_data_url")
