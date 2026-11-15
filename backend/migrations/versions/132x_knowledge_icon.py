"""Save optional knowledge base icons."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "132x_knowledge_icon"
down_revision = "131w_knowledge_parent_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_bases", sa.Column("icon_selection", JSONB(none_as_null=True)))


def downgrade() -> None:
    op.drop_column("knowledge_bases", "icon_selection")
