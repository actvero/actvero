"""Channel-owned model mapping and routing; preserve all existing model policies."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "94o_channel_routing"
down_revision = "92m_merge_skills_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_channels",
        sa.Column(
            "routing", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM model_channels WHERE routing <> '{}'::jsonb")
    ):
        raise RuntimeError("已有渠道路由配置，不能无损回退")
    op.drop_column("model_channels", "routing")
