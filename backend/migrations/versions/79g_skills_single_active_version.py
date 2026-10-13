"""Keep at most one published version per skill without deleting historical packages.

Revision ID: 79g_skills_single
Revises: 79f_skills
"""

import sqlalchemy as sa
from alembic import op

revision = "79g_skills_single"
down_revision = "79f_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("LOCK TABLE skills, skill_versions IN SHARE ROW EXCLUSIVE MODE")
    # Preserve an explicitly selected, published default. Otherwise retain the latest
    # publication, using creation time and id as deterministic tie-breakers.
    op.execute(
        """
        WITH ranked AS (
            SELECT v.id, row_number() OVER (
                PARTITION BY v.skill_id
                ORDER BY CASE WHEN v.id = s.default_version_id THEN 0 ELSE 1 END,
                         v.published_at DESC NULLS LAST, v.created_at DESC, v.id DESC
            ) AS position
            FROM skill_versions v JOIN skills s ON s.id = v.skill_id
            WHERE v.status = 'published'
        )
        UPDATE skill_versions v SET status = 'withdrawn'
        FROM ranked r WHERE v.id = r.id AND r.position > 1
        """
    )
    op.execute(
        """
        UPDATE skills s SET default_version_id = (
            SELECT v.id FROM skill_versions v
            WHERE v.skill_id = s.id AND v.status = 'published'
        ), revision = revision + 1
        """
    )
    op.create_index(
        "uq_skill_versions_one_published",
        "skill_versions",
        ["skill_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )


def downgrade() -> None:
    # Historical states are not re-published on downgrade. All packages remain intact.
    op.drop_index("uq_skill_versions_one_published", table_name="skill_versions")
