"""Personal cross-capability access credentials and attribution; no plaintext secrets."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "87h_access_keys"
down_revision = "86g_llm_settlement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "access_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("member_id", sa.Uuid(), sa.ForeignKey("memberships.id"), nullable=False),
        sa.Column("identity_id", sa.Uuid(), sa.ForeignKey("login_identities.id"), nullable=False),
        sa.Column("creation_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("hint", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("grants", postgresql.JSONB(), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("managed_disabled", sa.Boolean(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("member_id", "creation_id"),
    )
    for column in ("tenant_id", "member_id"):
        op.create_index("ix_access_keys_" + column, "access_keys", [column])
    op.create_table(
        "access_key_policies",
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("max_days", sa.Integer()),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    for table in ("llm_calls", "mcp_activities"):
        op.add_column(table, sa.Column("access_key_id", sa.Uuid(), sa.ForeignKey("access_keys.id")))
        op.create_index("ix_" + table + "_access_key_id", table, ["access_key_id"])


def downgrade() -> None:
    for table in ("llm_calls", "mcp_activities"):
        op.drop_index("ix_" + table + "_access_key_id", table_name=table)
        op.drop_column(table, "access_key_id")
    op.drop_table("access_key_policies")
    op.drop_table("access_keys")
