"""Replace per-model application grants with an organization-wide model switch."""

import sqlalchemy as sa
from alembic import op

revision = "134z_application_model_access"
down_revision = "133y_application_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "integration_applications",
        sa.Column("models_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Preserve the old grants for rollback. A grant for one model does not
    # authorize all current and future models.
    op.alter_column(
        "integration_applications", "model_grants", server_default=sa.text("'{}'::jsonb")
    )
    op.execute(
        "UPDATE integration_applications SET version = version + 1 WHERE model_grants <> '{}'"
    )


def downgrade() -> None:
    op.drop_column("integration_applications", "models_enabled")
    op.alter_column("integration_applications", "model_grants", server_default=None)
