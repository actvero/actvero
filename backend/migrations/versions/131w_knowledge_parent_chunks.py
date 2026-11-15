"""Store versioned parent contexts for knowledge retrieval."""

import sqlalchemy as sa
from alembic import op

revision = "131w_knowledge_parent_chunks"
down_revision = "130v_knowledge_retrieval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("knowledge_generations", sa.Column("character_count", sa.Integer()))
    op.create_table(
        "knowledge_parent_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "generation_id",
            sa.Uuid(),
            sa.ForeignKey("knowledge_generations.id"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_parent_chunks_generation_id", "knowledge_parent_chunks", ["generation_id"]
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column("parent_id", sa.Uuid(), sa.ForeignKey("knowledge_parent_chunks.id")),
    )


def downgrade() -> None:
    op.execute("UPDATE knowledge_bases SET chunking = chunking - 'structure' - 'child_chars'")
    op.execute("UPDATE knowledge_generations SET chunking = chunking - 'structure' - 'child_chars'")
    op.drop_column("knowledge_chunks", "parent_id")
    op.drop_table("knowledge_parent_chunks")
    op.drop_column("knowledge_generations", "character_count")
