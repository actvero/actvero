"""Store the optional catalog previews for each workbench version."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "126r_workbench_version_previews"
down_revision = "125r_workbench_version_icon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workbench_versions", sa.Column("preview_data_urls", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("workbench_versions", "preview_data_urls")
