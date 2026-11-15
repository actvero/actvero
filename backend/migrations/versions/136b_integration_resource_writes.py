"""Add organization application write grants and stable external resource ownership."""

import sqlalchemy as sa
from alembic import op

revision = "136b_integration_resource_writes"
down_revision = "135a_application_capabilities"
branch_labels = None
depends_on = None

FIELDS = ("mcp_write_enabled", "skills_write_enabled", "experts_write_enabled")


def upgrade() -> None:
    for field in FIELDS:
        op.add_column(
            "integration_applications",
            sa.Column(field, sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.create_table(
        "integration_resource_sources",
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("integration_applications.id"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(12), primary_key=True),
        sa.Column("source_id", sa.String(160), primary_key=True),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("kind", "resource_id"),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM integration_resource_sources)")):
        raise RuntimeError("存在应用推送记录，请使用升级前备份回退")
    op.drop_table("integration_resource_sources")
    for field in reversed(FIELDS):
        op.drop_column("integration_applications", field)
