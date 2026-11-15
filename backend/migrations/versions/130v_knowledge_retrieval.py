"""Store a retrieval policy for each knowledge base."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "130v_knowledge_retrieval"
down_revision = "129u_knowledge_org_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_bases", sa.Column("retrieval", JSONB(none_as_null=True)))


def downgrade() -> None:
    op.drop_column("knowledge_bases", "retrieval")
