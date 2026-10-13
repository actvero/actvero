"""Relocation needs exact authority, snapshot and subjects; never matches emails."""

from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from test_identity_access import env as identity_environment

from app.modules.auth import issuer_migration as service
from app.modules.auth.models import WebSession
from app.modules.tenants.models import Installation
from app.modules.users.models import LoginIdentity

env = identity_environment
pytestmark = pytest.mark.asyncio
TARGET = "http://127.0.0.1:5194/identity/realms/actvero"
PROOF = {"realm_id": "same-realm", "keys": ["same-signing-authority"]}


async def preview(env, monkeypatch):
    actor = await env.client()
    monkeypatch.setattr(service, "realm_proof", AsyncMock(return_value=PROOF))
    env.provider.admin = AsyncMock(
        return_value=httpx.Response(200, json={"id": actor.identity.subject})
    )
    async with env.sessions() as db:
        install = await db.get(Installation, 1)
        install.issuer = env.provider.settings.oidc_issuer
        install.subject = actor.identity.subject
        await db.commit()
        manifest = await service.prepare(db, env.provider, TARGET)
    env.provider.settings.oidc_issuer = TARGET
    return actor, manifest


async def test_exact_relocation_preserves_ids_brand_members_and_replay(env, monkeypatch):  # noqa: F811
    actor, manifest = await preview(env, monkeypatch)
    async with env.sessions() as db:
        install = await db.get(Installation, 1)
        instance = install.instance_id
        assert await service.relocate(db, env.provider, manifest) == "applied"
        identity = await db.get(LoginIdentity, actor.identity.id, populate_existing=True)
        assert identity.issuer == TARGET
        assert identity.user_id == actor.user.id and identity.subject == actor.identity.subject
        install = await db.get(Installation, 1, populate_existing=True)
        assert install.issuer == TARGET and install.instance_id == instance
        session = await db.scalar(select(WebSession).where(WebSession.identity_id == identity.id))
        assert session.tokens is None and session.requires_reauth
        assert await service.relocate(db, env.provider, manifest) == "already_applied"


@pytest.mark.parametrize("failure", ["realm", "keys", "subject", "snapshot", "collision"])
async def test_relocation_rejects_wrong_authority_and_changed_mapping_without_merging(
    env, monkeypatch, failure
):  # noqa: F811
    actor, manifest = await preview(env, monkeypatch)
    if failure in {"realm", "keys"}:
        monkeypatch.setattr(
            service,
            "realm_proof",
            AsyncMock(
                return_value=PROOF
                | {
                    "realm_id" if failure == "realm" else "keys": "different"
                    if failure == "realm"
                    else ["different"]
                }
            ),
        )
    if failure == "subject":
        env.provider.admin.return_value = httpx.Response(200, json={"id": "another-subject"})
    async with env.sessions() as db:
        if failure == "snapshot":
            identity = await db.get(LoginIdentity, actor.identity.id)
            identity.subject = "changed-after-preview"
            await db.commit()
        if failure == "collision":
            db.add(
                LoginIdentity(user_id=actor.user.id, issuer=TARGET, subject=actor.identity.subject)
            )
            await db.commit()
        with pytest.raises(ValueError):
            await service.relocate(db, env.provider, manifest)
        await db.rollback()
        assert (await db.get(LoginIdentity, actor.identity.id)).issuer == manifest["source"]


@pytest.mark.parametrize(
    "target",
    [
        "http://external.test/realms/actvero",
        TARGET + "?token=x",
        TARGET + "/",
        "https://identity.test/realms/other",
    ],
)
async def test_relocation_origin_and_realm_constraints(target):
    with pytest.raises(ValueError):
        service.validate_relocation("http://127.0.0.1:5196/realms/actvero", target)


async def test_relocation_replay_rejects_changed_installation(env, monkeypatch):  # noqa: F811
    actor, manifest = await preview(env, monkeypatch)
    async with env.sessions() as db:
        assert await service.relocate(db, env.provider, manifest) == "applied"
        install = await db.get(Installation, 1, populate_existing=True)
        install.subject = "changed-after-apply"
        await db.commit()
        with pytest.raises(ValueError):
            await service.relocate(db, env.provider, manifest)
        await db.rollback()
        assert (await db.get(LoginIdentity, actor.identity.id)).issuer == TARGET
