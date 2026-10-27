"""Merge independent gateway and client distribution migration histories."""

revision = "121p_gateway_distribution"
down_revision = ("120o_quota_assignments", "119n_download_only_releases")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
