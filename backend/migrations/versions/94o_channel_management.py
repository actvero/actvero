"""Persist versioned channel connections and independent management settings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "94o_channel_management"
down_revision = "93n_model_binding_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_channels",
        sa.Column("connection", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "model_channels",
        sa.Column("manual_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "model_channels",
        sa.Column(
            "automatic_protection",
            postgresql.JSONB(),
            nullable=False,
            server_default='{"enabled":true}',
        ),
    )
    op.add_column("model_channels", sa.Column("test_defaults", postgresql.JSONB(), nullable=True))
    op.add_column("model_channels", sa.Column("routing_version", sa.Integer(), nullable=True))
    # Frozen migration: preserve old bases byte-for-byte, including proxy/version
    # prefixes. No resolver or provider-default imports that might later change.
    op.execute(
        sa.text(
            "UPDATE model_channels SET connection = jsonb_build_object("
            "'address_mode', 'legacy_api_base', 'legacy_base_url', base_url, "
            "'resolver_version', 1), routing_version = version"
        )
    )
    for name in ("connection", "manual_enabled", "automatic_protection"):
        op.alter_column("model_channels", name, server_default=None)
    op.create_table(
        "llm_mutation_receipts",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("scope", sa.String(60), primary_key=True),
        sa.Column("request_id", sa.Uuid(), primary_key=True),
        sa.Column("payload_digest", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    raise RuntimeError(
        "渠道状态及幂等回执不可自动删除；停止新流量后按已演练备份恢复，或保留数据前滚修复"
    )
