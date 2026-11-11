"""Separate model facts from member publication without changing resource identities."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "122q_gateway_parameters"
down_revision = "121p_gateway_distribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "newapi_model_parameters",
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("model_name", sa.String(128), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("configuration", JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""
        INSERT INTO newapi_model_parameters
          (tenant_id, model_name, version, configuration, updated_at)
        SELECT tenant_id, slug, 1,
          (configuration - ARRAY[
            'name','slug','access','chat_policy','bindings','routing','budget_price','operations'
          ])
          || jsonb_build_object(
            'capability_mode', COALESCE(
              configuration->'gateway'->'capability_mode', '"auto"'::jsonb),
            'source', COALESCE(configuration->'gateway'->'capability_source', '{}'::jsonb)
          ),
          now()
        FROM llm_models WHERE jsonb_typeof(configuration->'gateway') = 'object'
    """)
    op.execute("""
        UPDATE llm_models SET configuration = jsonb_set(
          configuration, '{gateway,capability_source}',
          COALESCE(configuration->'gateway'->'capability_source', '{}'::jsonb)
          || '{"independent_parameters":"true"}'::jsonb
        ) WHERE jsonb_typeof(configuration->'gateway') = 'object'
    """)


def downgrade() -> None:
    op.drop_table("newapi_model_parameters")
