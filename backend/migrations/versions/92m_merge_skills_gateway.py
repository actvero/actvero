"""Join the independently shipped Skills and model gateway migration branches."""

revision = "92m_merge_skills_gateway"
down_revision = ("79j_skill_categories", "91l_model_import_receipts")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
