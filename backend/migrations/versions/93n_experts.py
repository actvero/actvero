"""Expert drafts, immutable releases and independently managed categories.

Revision ID: 93n_experts
Revises: 92m_merge_skills_gateway
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "93n_experts"
down_revision = "92m_merge_skills_gateway"
branch_labels = None
depends_on = None

SEEDS = (
    ("office", "办公协同"),
    ("engineering", "工程开发"),
    ("design", "设计创意"),
    ("content", "内容创作"),
    ("data", "数据分析"),
    ("education", "教育学习"),
    ("lifestyle", "生活服务"),
    ("general", "通用"),
    ("uncategorized", "未分类"),
)


def upgrade() -> None:
    op.create_table(
        "expert_categories",
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
                "INSERT INTO expert_categories (tenant_id, id, name, name_key, position, revision) "
                "SELECT id, :key, :name, :name, :position, 1 FROM tenants"
            ),
            {"key": key, "name": name, "position": position},
        )
    op.create_table(
        "experts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("category", sa.String(36), nullable=False),
        sa.Column("draft", JSONB(), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("member_ids", JSONB(), nullable=False),
        sa.Column("current_release_id", sa.Uuid(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("metadata_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "category"],
            ["expert_categories.tenant_id", "expert_categories.id"],
            name="fk_experts_category",
        ),
    )
    op.create_index("ix_experts_tenant_id", "experts", ["tenant_id"])
    op.create_table(
        "expert_releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("expert_id", sa.Uuid(), sa.ForeignKey("experts.id"), nullable=False),
        sa.Column("version", sa.String(30), nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("manifest", JSONB(), nullable=False),
        sa.Column("dependency_refs", JSONB(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("release_notes", sa.Text(), nullable=False),
        sa.Column("publisher_name", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("expert_id", "version"),
    )
    op.create_index("ix_expert_releases_expert_id", "expert_releases", ["expert_id"])


def downgrade() -> None:
    op.drop_table("expert_releases")
    op.drop_table("experts")
    op.drop_table("expert_categories")
