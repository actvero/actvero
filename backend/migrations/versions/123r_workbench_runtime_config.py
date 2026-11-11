"""Store organization runtime values and per-version configuration declarations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "123r_workbench_runtime_config"
down_revision = "122r_workbenches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workbenches",
        sa.Column("config_values", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "workbench_versions",
        sa.Column("config_fields", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.alter_column("workbenches", "config_values", server_default=None)
    op.alter_column("workbench_versions", "config_fields", server_default=None)


def downgrade() -> None:
    op.drop_column("workbench_versions", "config_fields")
    op.drop_column("workbenches", "config_values")
