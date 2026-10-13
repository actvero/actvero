"""Historical diagnostic lease release stays version-safe after Router migration."""

from datetime import timedelta

import pytest
from test_channel_health import catalog, channel
from test_identity_access import env as identity_env

from app.modules.auth.service import now
from app.modules.llm import routing
from app.modules.llm.diagnostic_health import RecoveryLease, release_recovery

pytestmark = pytest.mark.asyncio
env = identity_env


async def test_old_recovery_release_keeps_equal_timestamp_new_lease(env):
    admin = await env.client()
    async with env.sessions() as db:
        item = channel(admin.tenant.id)
        model, config = catalog(admin.tenant.id, [item], mode="fixed")
        db.add_all([item, model])
        await db.commit()
        binding = config.bindings[0]
        health = await routing.ensure(
            db,
            admin.tenant.id,
            routing.health_key(admin.tenant.id, model.id, config.kind, binding),
            routing.fingerprint(config, binding, item),
        )
        health.probe_until = now() + timedelta(seconds=30)
        routing.advance(health)
        lease = RecoveryLease(
            tenant_id=admin.tenant.id,
            actor_member_id=admin.member.id,
            model_id=model.id,
            model_version=model.version,
            binding_id=binding.binding_id,
            channel_id=item.id,
            channel_version=item.version,
            operation="embedding",
            upstream_id="upstream",
            health_key=health.id,
            fingerprint=health.fingerprint,
            credential_fingerprint=routing.credential_fingerprint(item),
            health_generation=health.health_generation,
            credential_generation=0,
            probe_until=health.probe_until,
        )
        routing.advance(health)  # New holder has the same until, but a later generation.
        await release_recovery(db, lease)
        assert health.probe_until == lease.probe_until
        await db.commit()
