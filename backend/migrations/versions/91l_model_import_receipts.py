"""Receipts for atomic, idempotent channel model imports; no model rewrites."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "91l_model_import_receipts"
down_revision = "90k_model_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_model_import_receipts",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM llm_model_import_receipts")):
        raise RuntimeError("已有模型导入回执，不能无损回退")
    op.drop_table("llm_model_import_receipts")
