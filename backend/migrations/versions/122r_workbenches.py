"""Store organization workbenches and their immutable package versions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "122r_workbenches"
down_revision = "121p_gateway_distribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workbenches",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("package_name", sa.String(214), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("member_ids", JSONB(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "package_name"),
    )
    op.create_index("ix_workbenches_tenant_id", "workbenches", ["tenant_id"])
    op.create_table(
        "workbench_versions",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "workbench_id",
            sa.UUID(),
            sa.ForeignKey("workbenches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("dsh_requirement", sa.String(160), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=False),
        sa.Column("uploader_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("workbench_id", "version"),
    )
    op.create_index("ix_workbench_versions_workbench_id", "workbench_versions", ["workbench_id"])
    op.create_index(
        "uq_workbench_versions_one_published",
        "workbench_versions",
        ["workbench_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_table(
        "workbench_packages",
        sa.Column(
            "version_id",
            sa.UUID(),
            sa.ForeignKey("workbench_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("data", sa.LargeBinary(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workbench_packages")
    op.drop_table("workbench_versions")
    op.drop_table("workbenches")
