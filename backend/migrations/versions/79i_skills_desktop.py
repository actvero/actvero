"""Single skill category and desktop distribution provenance.

Revision ID: 79i_skills_desktop
Revises: 79h_skills_icons
"""

import sqlalchemy as sa
from alembic import op

revision = "79i_skills_desktop"
down_revision = "79h_skills_icons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skills",
        sa.Column("category", sa.String(30), nullable=False, server_default="uncategorized"),
    )
    op.create_check_constraint(
        "ck_skills_category",
        "skills",
        "category IN ('office','development','data','content','design',"
        "'research','productivity','other','uncategorized')",
    )
    op.alter_column("skills", "category", server_default=None)
    op.add_column("skill_distributions", sa.Column("device_session_id", sa.Uuid(), nullable=True))
    op.add_column("skill_distributions", sa.Column("client_version", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("skill_distributions", "client_version")
    op.drop_column("skill_distributions", "device_session_id")
    op.drop_constraint("ck_skills_category", "skills", type_="check")
    op.drop_column("skills", "category")
