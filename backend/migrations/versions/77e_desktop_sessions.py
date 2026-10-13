"""Independent desktop sessions and single-use native login attempts."""

import sqlalchemy as sa
from alembic import op

revision = "77e_desktop_sessions"
down_revision = "76d_direct_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("identity_id", sa.Uuid(), sa.ForeignKey("login_identities.id"), nullable=False),
        sa.Column("client_id", sa.String(100), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("os", sa.String(20), nullable=False),
        sa.Column("app_version", sa.String(50), nullable=False),
        *[
            sa.Column(n, sa.DateTime(timezone=True), nullable=False)
            for n in (
                "authenticated_at",
                "created_at",
                "last_active_at",
                "expires_at",
                "idle_expires_at",
            )
        ],
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_device_sessions_identity_id", "device_sessions", ["identity_id"])
    op.create_table(
        "device_tokens",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("device_sessions.id"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("request_id", sa.Uuid()),
        sa.Column("response", sa.Text()),
        sa.Column("response_until", sa.DateTime(timezone=True)),
        sa.Column("successor_hash", sa.String(64)),
    )
    op.create_index("ix_device_tokens_session_id", "device_tokens", ["session_id"])
    op.create_table(
        "desktop_logins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("challenge", sa.String(43), nullable=False),
        sa.Column("redirect_uri", sa.String(200), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("os", sa.String(20), nullable=False),
        sa.Column("app_version", sa.String(50), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.Column("cancelled", sa.Boolean(), nullable=False),
        sa.Column("code_hash", sa.String(64)),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("device_sessions.id")),
        sa.Column("response", sa.Text()),
        sa.Column("response_until", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_desktop_logins_expires_at", "desktop_logins", ["expires_at"])


def downgrade() -> None:
    op.drop_table("desktop_logins")
    op.drop_table("device_tokens")
    op.drop_table("device_sessions")
