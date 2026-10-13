"""Skill presentation icons, preserving original packages and publication state.

Revision ID: 79h_skills_icons
Revises: 79g_skills_single
"""

import sqlalchemy as sa
from alembic import op
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.modules.skills.packages import inspect_package

revision = "79h_skills_icons"
down_revision = "79g_skills_single"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column(
            "icon_selection",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text('\'{"source":"auto"}\'::jsonb'),
        ),
    )
    op.add_column(
        "skill_versions", sa.Column("package_icon", sa.Text(), nullable=False, server_default="")
    )
    op.add_column(
        "skill_versions", sa.Column("icon_warning", sa.Text(), nullable=False, server_default="")
    )
    # Inspect each immutable package once, one row at a time. Never extract or rewrite it.
    bind = op.get_bind()
    ids = bind.execute(sa.text("SELECT version_id FROM skill_packages")).scalars().all()
    for version_id in ids:
        data = bind.execute(
            sa.text("SELECT data FROM skill_packages WHERE version_id=:id"), {"id": version_id}
        ).scalar_one()
        try:
            package = inspect_package(bytes(data))
            image, warning = package.package_icon, package.icon_warning
        except HTTPException:
            image, warning = "", "历史包图标无法读取，可在技能设置中选择图标。"
        bind.execute(
            sa.text(
                "UPDATE skill_versions SET package_icon=:image, icon_warning=:warning WHERE id=:id"
            ),
            {"id": version_id, "image": image, "warning": warning},
        )
    for table, field in (
        ("skills", "icon_selection"),
        ("skill_versions", "package_icon"),
        ("skill_versions", "icon_warning"),
    ):
        op.alter_column(table, field, server_default=None)


def downgrade() -> None:
    op.drop_column("skill_versions", "icon_warning")
    op.drop_column("skill_versions", "package_icon")
    op.drop_column("skills", "icon_selection")
