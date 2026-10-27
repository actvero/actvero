"""Upgrade legacy priority matches without changing clocks or historical settlement."""

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from test_identity_access import env as identity_env
from test_quota_accounting_audit import clock, entry, setup
from test_quota_policies import create, hours

from app.modules.llm.models import QuotaClock, UsageSettlement
from app.modules.members.models import Membership
from app.modules.quota.models import QuotaAssignment, QuotaPolicy
from app.modules.quota.service import matching_policies

env = identity_env


@pytest.mark.asyncio
async def test_upgrade_preserves_current_policy_paused_assignments_and_accounting(env):
    admin, default, model, channels = await setup(env)
    member = await env.client(role="member", tenant=admin.tenant)
    paused = await env.client(role="member", tenant=admin.tenant)
    low = await create(admin, name="旧低优先级", is_default=False, rules=[hours("200")])
    high = await create(admin, name="旧高优先级", is_default=False, rules=[hours("500")])
    stamp = datetime.now(UTC)
    call = await entry(env, admin, model, channels, stamp, status="settled", amount="0.2")
    await clock(env, admin, stamp - timedelta(minutes=5))
    async with env.sessions() as db:
        (await db.get(Membership, paused.member.id)).status = "paused"
        saved_clock = dict((await db.get(QuotaClock, admin.member.id)).windows)
        saved_entry = await db.get(UsageSettlement, call)
        historical = (
            saved_entry.amount,
            saved_entry.ratio,
            saved_entry.policy_snapshot,
            saved_entry.created_at,
        )
        await db.execute(text("DROP TABLE quota_assignments"))
        await db.execute(
            text("ALTER TABLE quota_policies ADD COLUMN priority integer NOT NULL DEFAULT 0")
        )
        await db.execute(
            text(
                "ALTER TABLE quota_policies ADD COLUMN member_ids "
                "jsonb NOT NULL DEFAULT '[]'::jsonb"
            )
        )
        for policy, priority in ((low, 10), (high, 20)):
            await db.execute(
                text(
                    "UPDATE quota_policies SET priority=:priority, "
                    "member_ids=CAST(:members AS jsonb) WHERE id=:id"
                ),
                {
                    "priority": priority,
                    "members": json.dumps([str(member.member.id), str(paused.member.id)]),
                    "id": policy["id"],
                },
            )
        await db.execute(
            text("ALTER TABLE quota_policies DROP COLUMN is_default, DROP COLUMN mode")
        )
        await db.execute(
            text(
                "CREATE UNIQUE INDEX uq_quota_priority ON quota_policies "
                "(tenant_id, priority) WHERE NOT archived"
            )
        )
        connection = await db.connection()

        def migrate(sync):
            spec = importlib.util.spec_from_file_location(
                "quota_assignments", Path("migrations/versions/120o_quota_assignments.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.op = Operations(MigrationContext.configure(sync))
            module.upgrade()

        await connection.run_sync(migrate)
        await db.commit()
        db.expire_all()
        assert (await matching_policies(db, admin.tenant.id, member.member.id))[0].id == UUID(
            high["id"]
        )
        assert (await matching_policies(db, admin.tenant.id, admin.member.id))[0].id == UUID(
            default["id"]
        )
        assert (await db.get(QuotaAssignment, paused.member.id)).policy_id == UUID(high["id"])
        assert await matching_policies(db, admin.tenant.id, paused.member.id) == []
        assert (await db.get(QuotaClock, admin.member.id)).windows == saved_clock
        row = await db.get(UsageSettlement, call)
        assert (row.amount, row.ratio, row.policy_snapshot, row.created_at) == historical
        assert (await db.get(QuotaPolicy, UUID(high["id"]))).version == high["version"]
