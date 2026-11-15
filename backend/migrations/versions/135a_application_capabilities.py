"""Add app capability switches and application-attributed resource activity."""

import sqlalchemy as sa
from alembic import op

revision = "135a_application_capabilities"
down_revision = "134z_application_model_access"
branch_labels = None
depends_on = None

CAPABILITIES = ("mcp", "skills", "experts", "knowledge")
HUMAN_CALL = (
    "source <> 'application' AND actor_id IS NOT NULL "
    "AND application_id IS NULL AND integration_key_id IS NULL"
)
APP_CALL = "actor_id IS NULL AND application_id IS NOT NULL AND integration_key_id IS NOT NULL"


def upgrade() -> None:
    for capability in CAPABILITIES:
        op.add_column(
            "integration_applications",
            sa.Column(
                f"{capability}_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )
    op.add_column(
        "audit_events",
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("integration_applications.id")),
    )
    op.alter_column("audit_events", "actor_id", nullable=True)
    op.create_check_constraint(
        "ck_audit_actor", "audit_events", "(actor_id IS NULL) <> (application_id IS NULL)"
    )
    op.add_column(
        "mcp_activities",
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("integration_applications.id")),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("application_id", sa.Uuid(), sa.ForeignKey("integration_applications.id")),
    )
    op.add_column("knowledge_bases", sa.Column("creation_id", sa.Uuid()))
    op.add_column("knowledge_bases", sa.Column("creation_fingerprint", sa.String(64)))
    op.create_unique_constraint(
        "uq_knowledge_application_creation", "knowledge_bases", ["application_id", "creation_id"]
    )
    op.add_column(
        "knowledge_generations",
        sa.Column("actor_integration_key_id", sa.Uuid(), sa.ForeignKey("integration_keys.id")),
    )
    op.alter_column("knowledge_generations", "actor_member_id", nullable=True)
    op.create_check_constraint(
        "ck_knowledge_generation_actor",
        "knowledge_generations",
        "(actor_member_id IS NULL) <> (actor_integration_key_id IS NULL)",
    )
    op.drop_constraint("ck_llm_call_principal", "llm_calls", type_="check")
    op.create_check_constraint(
        "ck_llm_call_principal",
        "llm_calls",
        f"(source IN ('application', 'knowledge_index', 'knowledge_search') AND {APP_CALL}) "
        f"OR ({HUMAN_CALL})",
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("knowledge_bases", "audit_events", "mcp_activities"):
        if bind.scalar(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE application_id IS NOT NULL)")
        ):
            raise RuntimeError("存在应用集成资源或活动记录，请使用升级前备份回退")
    op.drop_constraint("ck_llm_call_principal", "llm_calls", type_="check")
    op.create_check_constraint(
        "ck_llm_call_principal",
        "llm_calls",
        f"(source = 'application' AND {APP_CALL}) OR ({HUMAN_CALL})",
    )
    op.drop_constraint("ck_knowledge_generation_actor", "knowledge_generations", type_="check")
    op.alter_column("knowledge_generations", "actor_member_id", nullable=False)
    op.drop_column("knowledge_generations", "actor_integration_key_id")
    op.drop_constraint("uq_knowledge_application_creation", "knowledge_bases", type_="unique")
    for column in ("creation_fingerprint", "creation_id", "application_id"):
        op.drop_column("knowledge_bases", column)
    op.drop_column("mcp_activities", "application_id")
    op.drop_constraint("ck_audit_actor", "audit_events", type_="check")
    op.alter_column("audit_events", "actor_id", nullable=False)
    op.drop_column("audit_events", "application_id")
    for capability in reversed(CAPABILITIES):
        op.drop_column("integration_applications", f"{capability}_enabled")
