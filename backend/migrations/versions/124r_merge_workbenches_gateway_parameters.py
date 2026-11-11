"""Join the workbench and gateway model parameter migration histories."""

revision = "124r_workbenches_gateway"
down_revision = ("123r_workbench_runtime_config", "122q_gateway_parameters")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
