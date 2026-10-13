from uuid import UUID

import pytest
from sqlalchemy import select
from test_access_keys import ADMIN, OWN, create, headers, identity
from test_desktop import native_client
from test_identity_access import env

from app.modules.access_keys.models import AccessKey
from app.modules.audit.models import AuditEvent

__all__ = ["env", "identity"]
pytestmark = pytest.mark.asyncio


async def test_owner_reveal_encryption_csrf_and_admin_boundaries(env):
    admin, member, other = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    key, _ = await create(member)
    target = "/" + key["key"]["id"]
    assert key["key"]["can_reveal"]
    result = await member.api.post(OWN + target + "/reveal", json={"version": 1})
    assert result.status_code == 200 and result.json()["secret"] == key["secret"]
    assert result.headers["cache-control"] == "no-store"
    assert (
        await member.api.post(
            OWN + target + "/reveal", json={"version": 1}, headers={"x-csrf-token": "wrong"}
        )
    ).status_code == 403
    assert (await other.api.post(OWN + target + "/reveal", json={"version": 1})).status_code == 404
    assert (
        await admin.api.post(ADMIN + target + "/reveal", json={"version": 1})
    ).status_code == 404
    assert (
        await member.api.post(ADMIN + target + "/reveal", json={"version": 1})
    ).status_code == 403
    assert (await member.api.post(OWN + target + "/reveal", json={"version": 9})).status_code == 409
    for actor, path in [(member, OWN), (admin, ADMIN)]:
        listing = await actor.api.get(path)
        assert key["secret"] not in listing.text and "sealed_secret" not in listing.text
        assert listing.json()["items"][0]["can_reveal"] == (actor == member)
    async with env.sessions() as db:
        stored = await db.get(AccessKey, UUID(key["key"]["id"]))
        assert stored.sealed_secret and key["secret"] not in stored.sealed_secret
        events = list(
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "access_key.reveal"))
        )
        assert len(events) == 1 and key["secret"] not in str(events[0].__dict__)
        stored.sealed_secret = None
        await db.commit()
    legacy = await member.api.post(OWN + target + "/reveal", json={"version": 1})
    assert legacy.status_code == 409
    assert not (await member.api.get(OWN)).json()["items"][0]["can_reveal"]
    async with native_client(env) as api:
        assert (
            await api.post(OWN + target + "/reveal", json={"version": 1}, headers=headers(key))
        ).status_code == 403


@pytest.mark.parametrize("admin_delete,revoked", [(False, False), (True, False), (True, True)])
async def test_delete_revokes_hides_preserves_audit_and_stale_writes(env, admin_delete, revoked):
    admin, member, other = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    key, _ = await create(member)
    target = "/" + key["key"]["id"]
    body = {"action": "delete", "version": 1}
    assert (await other.api.patch(OWN + target, json=body)).status_code == 404
    assert (
        await member.api.patch(OWN + target, json=body, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    if revoked:
        r = await member.api.patch(OWN + target, json={"version": 1, "action": "revoke"})
        assert r.status_code == 200
        assert (await member.api.patch(OWN + target, json=body)).status_code == 409
        body["version"] = 2
    actor, path = (admin, ADMIN) if admin_delete else (member, OWN)
    r = await actor.api.patch(path + target, json=body)
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    assert (await member.api.get(OWN)).json()["total"] == 0
    assert (await admin.api.get(ADMIN)).json()["total"] == 0
    assert (
        await member.api.post(OWN + target + "/reveal", json={"version": body["version"] + 1})
    ).status_code == 404
    assert (
        await actor.api.patch(
            path + target, json={"action": "enable", "version": body["version"] + 1}
        )
    ).status_code == 404
    async with env.sessions() as db:
        row = await db.get(AccessKey, UUID(key["key"]["id"]))
        assert row.deleted_at and row.revoked_at and not row.sealed_secret
        assert await db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.action == "access_key.delete", AuditEvent.target_id == row.id
            )
        )
    async with native_client(env) as api:
        assert (await api.get("/api/llm/v1/models", headers=headers(key))).status_code == 401


async def test_swapped_ciphertext_never_reveals_another_key(env):
    member = await env.client()
    a, _ = await create(member)
    b, _ = await create(member)
    async with env.sessions() as db:
        ra, rb = (
            await db.get(AccessKey, UUID(a["key"]["id"])),
            await db.get(AccessKey, UUID(b["key"]["id"])),
        )
        ra.sealed_secret = rb.sealed_secret
        await db.commit()
    r = await member.api.post(OWN + "/" + a["key"]["id"] + "/reveal", json={"version": 1})
    assert r.status_code == 503 and a["secret"] not in r.text and b["secret"] not in r.text
