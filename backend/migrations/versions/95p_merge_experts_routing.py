"""Merge Experts and channel routing histories without rewriting either branch."""

revision = "95p_merge_experts_routing"
down_revision = ("93n_experts", "94o_channel_routing")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
