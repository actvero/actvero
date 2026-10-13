"""Personal Web usage reads use real database isolation and loopback inference."""

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from llm_billing_helpers import billing
from test_access_keys import create, headers
from test_desktop import native_client
from test_identity_access import env as identity_env
from test_llm_execution import configured, payload, upstream
from test_mcp import listening

from app.modules.desktop.oidc import NativeIdentity
from app.modules.llm.models import QuotaClock, UsageSettlement
from app.modules.members.models import Membership

env = identity_env
pytestmark = pytest.mark.asyncio
OWN = "/api/v1/account/llm"


async def test_personal_windows_history_filters_and_isolation(env, monkeypatch):
    monkeypatch.setattr(NativeIdentity, "account_valid", AsyncMock(return_value=True))
    admin, member, other = (
        await env.client(),
        await env.client(role="member"),
        await env.client(role="member"),
    )
    assert (await member.api.get(OWN + "/quota")).json() == {
        "status": "unconfigured",
        "policy": None,
        "windows": [],
    }
    assert (await member.api.get(OWN + "/usage")).json() == {"total": 0, "items": []}
    await billing(admin)
    # Reading an unused quota must not start the first-use window.
    before = (await member.api.get(OWN + "/quota")).json()
    assert before["windows"][0]["started_at"] is None
    async with env.sessions() as db:
        assert await db.get(QuotaClock, member.member.id) is None
    app, _ = upstream()
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        key, _ = await create(member)
        other_key, _ = await create(other)
        async with native_client(env) as api:
            for actor_key in (key, other_key):
                r = await api.post(
                    "/api/llm/v1/chat/completions", headers=headers(actor_key), json=payload(model)
                )
                assert r.status_code == 200, r.text
            for suffix in ("/quota", "/usage"):
                assert (await api.get(OWN + suffix)).status_code == 401
                assert (await api.get(OWN + suffix, headers=headers(key))).status_code == 401
    own = await member.api.get(OWN + "/usage", params={"member_id": str(other.member.id)})
    assert own.status_code == 200 and own.json()["total"] == 1
    item = own.json()["items"][0]
    assert item["member_id"] == str(member.member.id) and item["status"] == "settled"
    assert item["points"] == "0.0244" and item["reserved_points"] == "0"
    async with env.sessions() as db:
        stored = await db.get(UsageSettlement, UUID(item["id"]))
        stored.reason = "private procurement reconciliation"
        await db.commit()
    own = (await member.api.get(OWN + "/usage")).json()
    assert own["items"][0]["reason"] == ""
    for field in ("amount", "price", "ratio", "currency", "channel_id", "upstream_id"):
        assert field not in own["items"][0]
    assert (await admin.api.get(OWN + "/usage")).json()["total"] == 0
    assert (await member.api.get(OWN + "/usage?state=review")).json()["total"] == 0
    assert (await member.api.get(OWN + "/usage?state=settled")).json()["total"] == 1
    assert (await member.api.get(OWN + "/usage?page=2")).json()["items"] == []
    assert (await member.api.get(OWN + "/usage?page=0")).status_code == 422
    assert (await member.api.get(OWN + "/usage?state=unknown")).status_code == 422
    quota = (
        await member.api.get(OWN + "/quota", params={"member_id": str(other.member.id)})
    ).json()
    admin_view = (await admin.api.get(f"/api/v1/llm/members/{member.member.id}/quota")).json()
    assert quota == admin_view
    assert quota["windows"][0]["used"] == item["points"]
    assert (await member.api.get(f"/api/v1/llm/members/{other.member.id}/quota")).status_code == 403


@pytest.mark.parametrize("status", ["paused", "removed"])
async def test_inactive_members_cannot_read_personal_usage(env, status):
    member = await env.client(role="member")
    async with env.sessions() as db:
        row = await db.get(Membership, member.member.id)
        row.status = status
        await db.commit()
    for suffix in ("/quota", "/usage"):
        assert (await member.api.get(OWN + suffix)).status_code == 403


async def test_unjoined_users_cannot_read_usage(env):
    await env.client()
    user = await env.client(joined=False)
    for suffix in ("/quota", "/usage"):
        assert (await user.api.get(OWN + suffix)).status_code == 403
