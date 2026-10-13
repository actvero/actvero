"""Immutable brand assets, shared presentation and identity synchronization."""

import sqlalchemy as sa
from alembic import op

revision = "111f_unified_branding"
down_revision = "110e_client_downloads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(30), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.add_column(
        "installation", sa.Column("branding_assets", sa.JSON(), nullable=False, server_default="{}")
    )
    op.add_column("installation", sa.Column("identity_branding_revision", sa.Uuid(), nullable=True))
    # Preserve the old bytes and UUID exactly, including already-sent mail URLs.
    op.execute(
        "INSERT INTO brand_assets (id, data, media_type) "
        "SELECT platform_logo_version, platform_logo_data, 'image/webp' FROM installation "
        "WHERE platform_logo_version IS NOT NULL AND platform_logo_data IS NOT NULL"
    )
    op.execute(
        "UPDATE installation SET branding_assets = "
        "json_build_object('mark_light', platform_logo_version::text) "
        "WHERE platform_logo_version IS NOT NULL AND platform_logo_data IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("installation", "identity_branding_revision")
    op.drop_column("installation", "branding_assets")
    op.drop_table("brand_assets")
