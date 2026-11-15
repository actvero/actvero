"""Add organization-owned applications, credentials and model call attribution."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "133y_application_integrations"
down_revision = "132x_knowledge_icon"
branch_labels = None
depends_on = None

SETTLEMENT = "ck_llm_settlement_quota_subject"
MEMBER_SUBJECT = "member_id IS NOT NULL AND conversion_id IS NOT NULL AND ratio IS NOT NULL"
ORGANIZATION_SUBJECT = "member_id IS NULL AND conversion_id IS NULL AND ratio IS NULL"
NO_REQUEST = "idempotency_key IS NULL AND request_fingerprint IS NULL"


def upgrade() -> None:
    op.create_table(
        "integration_applications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("model_grants", JSONB(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name"),
    )
    op.create_index(
        "ix_integration_applications_tenant_id", "integration_applications", ["tenant_id"]
    )
    op.create_table(
        "integration_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("integration_applications.id"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("hint", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_integration_keys_application_id", "integration_keys", ["application_id"])
    op.add_column(
        "llm_calls",
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("integration_applications.id")),
    )
    op.add_column(
        "llm_calls",
        sa.Column("integration_key_id", sa.Uuid(), sa.ForeignKey("integration_keys.id")),
    )
    op.alter_column("llm_calls", "actor_id", nullable=True)
    op.create_index("ix_llm_calls_application_id", "llm_calls", ["application_id"])
    op.create_check_constraint(
        "ck_llm_call_principal",
        "llm_calls",
        "(source = 'application' AND actor_id IS NULL AND application_id IS NOT NULL "
        "AND integration_key_id IS NOT NULL) OR (source <> 'application' "
        "AND actor_id IS NOT NULL AND application_id IS NULL AND integration_key_id IS NULL)",
    )
    op.add_column(
        "llm_settlements",
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("integration_applications.id")),
    )
    op.create_unique_constraint(
        "uq_llm_application_request",
        "llm_settlements",
        ["tenant_id", "application_id", "idempotency_key"],
    )
    op.drop_constraint(SETTLEMENT, "llm_settlements", type_="check")
    op.create_check_constraint(
        SETTLEMENT,
        "llm_settlements",
        f"({MEMBER_SUBJECT} AND application_id IS NULL) OR "
        f"({ORGANIZATION_SUBJECT} AND (application_id IS NOT NULL OR ({NO_REQUEST})))",
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM integration_applications)")):
        raise RuntimeError("应用集成已有数据，降级会丢失应用身份或调用归属。请使用升级前备份回退。")
    op.drop_constraint(SETTLEMENT, "llm_settlements", type_="check")
    op.create_check_constraint(
        SETTLEMENT,
        "llm_settlements",
        f"({MEMBER_SUBJECT}) OR ({ORGANIZATION_SUBJECT} AND {NO_REQUEST})",
    )
    op.drop_constraint("uq_llm_application_request", "llm_settlements", type_="unique")
    op.drop_column("llm_settlements", "application_id")
    op.drop_constraint("ck_llm_call_principal", "llm_calls", type_="check")
    op.drop_index("ix_llm_calls_application_id", table_name="llm_calls")
    op.drop_column("llm_calls", "integration_key_id")
    op.drop_column("llm_calls", "application_id")
    op.alter_column("llm_calls", "actor_id", nullable=False)
    op.drop_table("integration_keys")
    op.drop_table("integration_applications")
