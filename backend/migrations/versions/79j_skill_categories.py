"""Editable organization skill categories, preserving existing stable IDs.

Revision ID: 79j_skill_categories
Revises: 79i_skills_desktop
"""

import sqlalchemy as sa
from alembic import op

revision = "79j_skill_categories"
down_revision = "79i_skills_desktop"
branch_labels = None
depends_on = None

SEEDS = (
    ("office", "办公协同"),
    ("development", "开发工具"),
    ("data", "数据分析"),
    ("content", "内容创作"),
    ("design", "设计创意"),
    ("research", "知识检索"),
    ("productivity", "效率工具"),
    ("other", "其他"),
    ("uncategorized", "未分类"),
)


def upgrade() -> None:
    op.create_table(
        "skill_categories",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("name_key", sa.String(90), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "name_key"),
    )
    for position, (key, name) in enumerate(SEEDS):
        op.get_bind().execute(
            sa.text(
                "INSERT INTO skill_categories (tenant_id, id, name, name_key, position, revision) "
                "SELECT id, :key, :name, :name, :position, 1 FROM tenants"
            ),
            {"key": key, "name": name, "position": position},
        )
    op.drop_constraint("ck_skills_category", "skills", type_="check")
    op.alter_column("skills", "category", type_=sa.String(36), existing_type=sa.String(30))
    op.create_foreign_key(
        "fk_skills_category",
        "skills",
        "skill_categories",
        ["tenant_id", "category"],
        ["tenant_id", "id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_skills_category", "skills", type_="foreignkey")
    # Older releases can only represent the seed IDs. Packages/publications remain intact.
    op.execute(
        "UPDATE skills SET category='uncategorized', revision=revision+1 WHERE category NOT IN "
        "('office','development','data','content','design','research','productivity','other','uncategorized')"
    )
    op.alter_column("skills", "category", type_=sa.String(30), existing_type=sa.String(36))
    op.create_check_constraint(
        "ck_skills_category",
        "skills",
        "category IN ('office','development','data','content','design',"
        "'research','productivity','other','uncategorized')",
    )
    op.drop_table("skill_categories")
