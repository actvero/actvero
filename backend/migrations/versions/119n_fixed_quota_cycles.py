"""Replace calendar weeks with elapsed 168-hour cycles without refilling active budgets."""

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, insert

revision = "119n_fixed_quota_cycles"
down_revision = "118m_newapi_gateway"
branch_labels = None
depends_on = None


def upgrade() -> None:
    db = op.get_bind()
    stamp = db.scalar(sa.text("SELECT CURRENT_TIMESTAMP"))
    policies = sa.table(
        "quota_policies",
        sa.column("id", sa.UUID),
        sa.column("tenant_id", sa.UUID),
        sa.column("priority", sa.Integer),
        sa.column("member_ids", JSONB),
        sa.column("rules", JSONB),
        sa.column("archived", sa.Boolean),
        sa.column("version", sa.Integer),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    clocks = sa.table(
        "llm_quota_clocks",
        sa.column("member_id", sa.UUID),
        sa.column("tenant_id", sa.UUID),
        sa.column("windows", JSONB),
    )
    rows = list(db.execute(sa.select(policies).order_by(policies.c.priority.desc())).mappings())
    # Include paused members: pausing and resuming must not refill an existing budget.
    members = db.execute(sa.text("SELECT id, tenant_id FROM memberships")).mappings()
    for member in members:
        selected = next(
            (
                p
                for p in rows
                if not p["archived"]
                and p["tenant_id"] == member["tenant_id"]
                and (p["priority"] == 0 or str(member["id"]) in p["member_ids"])
            ),
            None,
        )
        week = (
            next((r for r in selected["rules"] if r["kind"] == "calendar_week"), None)
            if selected
            else None
        )
        if week is None:
            continue
        local = stamp.astimezone(ZoneInfo(week["timezone"]))
        day = local.date() - timedelta(days=(local.weekday() - week["week_start"]) % 7)
        start = datetime.combine(day, time(), local.tzinfo).astimezone(UTC)
        end = (datetime.combine(day, time(), local.tzinfo) + timedelta(days=7)).astimezone(UTC)
        windows = dict(
            db.scalar(sa.select(clocks.c.windows).where(clocks.c.member_id == member["id"])) or {}
        )
        old = windows.get("168")
        if old:
            old_start = datetime.fromisoformat(old["start"])
            old_end = (
                datetime.fromisoformat(old["end"])
                if old.get("end")
                else old_start + timedelta(hours=168)
            )
            if old_end > stamp:
                # A duplicate 168h + calendar rule becomes the stricter cap over
                # the union of both active intervals for this one transition.
                start, end = min(start, old_start), max(end, old_end)
        used = db.scalar(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM llm_settlements WHERE member_id=:member "
                "AND status IN ('reserved','review','settled') "
                "AND created_at>=:start AND created_at<:end)"
            ),
            {"member": member["id"], "start": start, "end": end},
        )
        if not used:
            continue  # An unused quota still starts on its first admission.
        windows["168"] = {"start": start.isoformat(), "end": end.isoformat()}
        db.execute(
            insert(clocks)
            .values(member_id=member["id"], tenant_id=member["tenant_id"], windows=windows)
            .on_conflict_do_update(index_elements=[clocks.c.member_id], set_={"windows": windows})
        )
    for row in rows:
        week = next((r for r in row["rules"] if r["kind"] == "calendar_week"), None)
        if week is None:
            continue
        rules = [r for r in row["rules"] if r["kind"] != "calendar_week" and r.get("hours") != 168]
        caps = [week["points"], *[r["points"] for r in row["rules"] if r.get("hours") == 168]]
        rules.append({"kind": "fixed_hours", "hours": 168, "points": min(caps, key=Decimal)})
        db.execute(
            policies.update()
            .where(policies.c.id == row["id"])
            .values(
                rules=rules,
                version=row["version"] + 1,
                updated_at=stamp,
            )
        )


def downgrade() -> None:
    raise RuntimeError(
        "Elapsed quota cycles cannot restore discarded calendar settings; "
        "restore a verified backup to downgrade."
    )
