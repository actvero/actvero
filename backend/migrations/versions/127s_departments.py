"""Add organization departments, membership links and resource department scopes."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "127s_departments"
down_revision = "126r_workbench_version_previews"
branch_labels = None
depends_on = None

RESOURCES = ("skills", "mcp_services", "experts", "workbenches")


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "parent_id"], ["departments.tenant_id", "departments.id"]
        ),
    )
    op.create_index("ix_departments_tenant_parent", "departments", ["tenant_id", "parent_id"])
    op.create_table(
        "department_members",
        sa.Column(
            "member_id",
            sa.Uuid(),
            sa.ForeignKey("memberships.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("department_id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "department_id"], ["departments.tenant_id", "departments.id"]
        ),
    )
    op.create_index(
        "ix_department_members_tenant_department",
        "department_members",
        ["tenant_id", "department_id"],
    )
    op.create_index(
        "uq_department_members_primary",
        "department_members",
        ["member_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )
    for table in RESOURCES:
        op.add_column(
            table,
            sa.Column(
                "department_grants", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
            ),
        )


def downgrade() -> None:
    op.execute(
        """
        UPDATE llm_models
        SET configuration = CASE
            WHEN configuration #>> '{access,audience}' = 'selected'
                AND COALESCE(configuration #> '{access,member_ids}', '[]'::jsonb) = '[]'::jsonb
            THEN jsonb_set(configuration, '{access}',
                ((configuration -> 'access') - 'department_grants')
                || '{"enabled": false, "audience": "administrators"}'::jsonb)
            ELSE configuration #- '{access,department_grants}'
        END,
        version = version + 1
        WHERE (configuration -> 'access') ? 'department_grants'
        """
    )
    for table in RESOURCES:
        op.drop_column(table, "department_grants")
    op.drop_table("department_members")
    op.drop_table("departments")
