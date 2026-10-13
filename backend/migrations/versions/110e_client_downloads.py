"""Deployment-scoped desktop releases, explicit recommendations and audit."""

import sqlalchemy as sa
from alembic import op

revision = "110e_client_downloads"
down_revision = "109d_management_cli"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "client_releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.String(50), nullable=False, unique=True),
        sa.Column("release_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("assets", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'withdrawn')", name="client_release_status"
        ),
        sa.CheckConstraint("revision > 0", name="client_release_revision"),
    )
    op.create_table(
        "client_recommendations",
        sa.Column("platform", sa.String(20), primary_key=True),
        sa.Column("architecture", sa.String(20), primary_key=True),
        sa.Column("release_id", sa.Uuid(), sa.ForeignKey("client_releases.id"), nullable=False),
        sa.CheckConstraint(
            "platform IN ('windows', 'macos')", name="client_recommendation_platform"
        ),
        sa.CheckConstraint(
            "architecture IN ('x64', 'arm64', 'universal')",
            name="client_recommendation_architecture",
        ),
        sa.CheckConstraint(
            "platform != 'windows' OR architecture != 'universal'",
            name="client_recommendation_target",
        ),
    )
    op.create_table(
        "client_release_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_name", sa.String(200), nullable=False),
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_client_release_events_release_id", "client_release_events", ["release_id"])


def downgrade() -> None:
    op.drop_table("client_release_events")
    op.drop_table("client_recommendations")
    op.drop_table("client_releases")
