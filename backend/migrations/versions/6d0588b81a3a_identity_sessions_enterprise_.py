"""identity sessions enterprise memberships invitations and audit

Revision ID: 6d0588b81a3a
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "6d0588b81a3a"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("actor_name", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_name", sa.String(length=320), nullable=False),
        sa.Column("result", sa.String(length=30), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_events_created_at"), "audit_events", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_audit_events_tenant_id"), "audit_events", ["tenant_id"], unique=False)
    op.create_table(
        "installation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("grant_hash", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_ciphertext", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("mail_status", sa.String(length=20), nullable=False),
        sa.Column("needs_activation", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("accepted_by", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_request_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'accepted', 'revoked', 'expired')"),
        sa.ForeignKeyConstraint(
            ["accepted_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_invitations_tenant_id"), "invitations", ["tenant_id"], unique=False)
    op.create_index(
        "uq_pending_invitation",
        "invitations",
        ["tenant_id", "email"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "login_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_index(
        op.f("ix_login_identities_user_id"), "login_identities", ["user_id"], unique=False
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("role IN ('administrator', 'member')"),
        sa.CheckConstraint("status IN ('active', 'paused', 'removed')"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id"),
    )
    op.create_index(op.f("ix_memberships_tenant_id"), "memberships", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False)
    op.create_table(
        "web_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("csrf", sa.String(length=64), nullable=False),
        sa.Column("identity_id", sa.Uuid(), nullable=True),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tokens", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("setup_hash", sa.String(length=64), nullable=True),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("invitation_hash", sa.String(length=64), nullable=True),
        sa.Column("login_state", sa.String(length=64), nullable=True),
        sa.Column("login_data", sa.String(), nullable=True),
        sa.Column("login_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["login_identities.id"],
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["invitations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        op.f("ix_web_sessions_expires_at"), "web_sessions", ["expires_at"], unique=False
    )
    op.execute("INSERT INTO installation (id) VALUES (1)")


def downgrade() -> None:
    op.drop_index(op.f("ix_web_sessions_expires_at"), table_name="web_sessions")
    op.drop_table("web_sessions")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_tenant_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(op.f("ix_login_identities_user_id"), table_name="login_identities")
    op.drop_table("login_identities")
    op.drop_index(
        "uq_pending_invitation",
        table_name="invitations",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(op.f("ix_invitations_tenant_id"), table_name="invitations")
    op.drop_table("invitations")
    op.drop_table("installation")
    op.drop_index(op.f("ix_audit_events_tenant_id"), table_name="audit_events")
    op.drop_index(op.f("ix_audit_events_created_at"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("users")
    op.drop_table("tenants")
    op.drop_table("rate_limits")
