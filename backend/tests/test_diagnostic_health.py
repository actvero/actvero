"""Explicit health recovery uses one binding and a leased local SDK diagnostic."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from test_identity_access import env as identity_env
from test_image_gateway import configure as configure_image
from test_llm_execution import configured as configure_chat
from test_llm_execution import upstream as chat_upstream
from test_llm_retrieval import configured as configure_retrieval
from test_llm_routing import update
from test_mcp import listening

from app.modules.auth.service import now
from app.modules.llm import channel_testing, routing
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.diagnostic_health import begin_recovery, finish_recovery, release_recovery
from app.modules.llm.models import ModelChannel, RouteHealth
from app.modules.llm.schemas import (
    ChannelChatProbe,
    ChannelEmbeddingProbe,
    ChannelImageProbe,
    ChannelRerankProbe,
    ChannelTestView,
    RankPreview,
    VectorPreview,
)
from app.modules.members.models import Membership
from app.modules.tenants.models import Tenant

env = identity_env
pytestmark = pytest.mark.asyncio


def chat_body(channel):
    return ChannelChatProbe(
        operation="chat",
        version=channel["version"],
        id="vendor-chat",
        prompt="fixture",
        max_output_tokens=50,
    )


def catalog_config(model):
    return CatalogInput.model_validate(
        {key: value for key, value in model.items() if key in CatalogInput.model_fields}
    )


async def claim(env, admin, model, channel, body):
    async with env.sessions() as db:
        lease = await begin_recovery(
            db,
            tenant_id=admin.tenant.id,
            actor_member_id=admin.member.id,
            model_id=UUID(model["id"]),
            model_version=model["version"],
            binding_id=UUID(model["bindings"][0]["binding_id"]),
            channel_id=UUID(channel["id"]),
            channel_version=channel["version"],
            body=body,
        )
        await db.commit()
    return lease


def success(operation="chat", **extra):
    return ChannelTestView(
        operation=operation,
        ok=True,
        message="本地测试成功",
        request_id=uuid4(),
        tested_at=now(),
        duration_ms=1,
        **extra,
    )


async def test_real_sdk_success_certifies_only_selected_binding_and_preserves_manual_gate(env):
    admin = await env.client()
    app, _ = chat_upstream()
    async with listening(app) as base:
        model, channels = await configure_chat(env, admin, base)
        channel = channels[0]
        model = await update(
            admin,
            model,
            access={"enabled": False, "audience": "organization"},
            bindings=[
                {**item, "enabled": False} if item["channel_id"] == channel["id"] else item
                for item in model["bindings"]
            ],
        )
        async with env.sessions() as db:
            row = await db.get(ModelChannel, UUID(channel["id"]))
            row.manual_enabled = False
            await db.scalar(select(Tenant.id).where(Tenant.id == admin.tenant.id).with_for_update())
            credentials = await routing.ensure(
                db,
                admin.tenant.id,
                routing.credential_key(row),
                routing.credential_fingerprint(row),
            )
            credentials.blocked = True
            await db.commit()
        body = chat_body(channel)
        lease = await claim(env, admin, model, channel, body)
        result = await channel_testing.execute(
            body,
            adapter="openai",
            base=base + "/a",
            key="test-secret",
            timeout=30,
            settings=env.provider.settings,
            request_id=uuid4(),
        )
        assert result.ok
        async with env.sessions() as db:
            assert await finish_recovery(db, lease, result=result)
            await db.commit()
        async with env.sessions() as db:
            selected = await db.get(RouteHealth, lease.health_key)
            other = await db.get(
                RouteHealth,
                routing.health_key(
                    admin.tenant.id,
                    UUID(model["id"]),
                    "chat",
                    catalog_config(model).for_operation("chat").bindings[1],
                ),
            )
            row = await db.get(ModelChannel, UUID(channel["id"]))
            credentials = await db.get(RouteHealth, routing.credential_key(row))
            assert selected.tested_at is not None and selected.probe_until is None
            assert other is None or other.tested_at is None
            assert row.manual_enabled is False
            assert credentials.blocked is False
        assert model["bindings"][0]["enabled"] is False


async def test_historical_cooldown_does_not_block_explicit_diagnostic(env):
    admin = await env.client()
    app, _ = chat_upstream()
    async with listening(app) as base:
        model, channels = await configure_chat(env, admin, base)
        channel = channels[0]
        config = catalog_config(model).for_operation("chat")
        binding = config.bindings[0]
        async with env.sessions() as db:
            await db.scalar(select(Tenant.id).where(Tenant.id == admin.tenant.id).with_for_update())
            row = await db.get(ModelChannel, UUID(channel["id"]))
            key = routing.health_key(admin.tenant.id, UUID(model["id"]), "chat", binding)
            health = await routing.ensure(
                db, admin.tenant.id, key, routing.fingerprint(config, binding, row)
            )
            health.cooldown_until = now() + timedelta(hours=2)
            await db.commit()
        lease = await claim(env, admin, model, channel, chat_body(channel))
        async with env.sessions() as db:
            health = await db.get(RouteHealth, key)
            assert health.probe_until == lease.probe_until and health.cooldown_until > now()


async def test_old_result_cannot_clear_new_holder_or_changed_model(env):
    admin = await env.client()
    app, _ = chat_upstream()
    async with listening(app) as base:
        model, channels = await configure_chat(env, admin, base)
        channel = channels[0]
        body = chat_body(channel)
        first = await claim(env, admin, model, channel, body)
        with pytest.raises(HTTPException) as busy:
            await claim(env, admin, model, channel, body)
        assert busy.value.status_code == 409
        async with env.sessions() as db:
            health = await db.get(RouteHealth, first.health_key)
            health.probe_until = now() - timedelta(seconds=1)
            await db.commit()
        second = await claim(env, admin, model, channel, body)
        async with env.sessions() as db:
            assert not await finish_recovery(db, first, result=success())
            await release_recovery(db, first)
            await db.commit()
        async with env.sessions() as db:
            health = await db.get(RouteHealth, second.health_key)
            assert health.probe_until == second.probe_until and health.tested_at is None
        model = await update(admin, model, name="改名后的模型")
        async with env.sessions() as db:
            assert not await finish_recovery(db, second, result=success())
            await db.commit()
        async with env.sessions() as db:
            health = await db.get(RouteHealth, second.health_key)
            assert health.tested_at is None and health.probe_until is None


async def test_credential_change_and_new_cooldown_cannot_be_certified(env):
    admin = await env.client()
    app, _ = chat_upstream()
    async with listening(app) as base:
        model, channels = await configure_chat(env, admin, base)
        channel = channels[0]
        first = await claim(env, admin, model, channel, chat_body(channel))
        async with env.sessions() as db:
            row = await db.get(ModelChannel, UUID(channel["id"]))
            row.sealed_key = "changed-during-test"
            await db.commit()
        async with env.sessions() as db:
            assert not await finish_recovery(db, first, result=success())
            await db.commit()
        async with env.sessions() as db:
            health = await db.get(RouteHealth, first.health_key)
            assert health.tested_at is None and health.probe_until is None
            row = await db.get(ModelChannel, UUID(channel["id"]))
            row.sealed_key = "test-secret"
            await db.commit()
        second = await claim(env, admin, model, channel, chat_body(channel))
        async with env.sessions() as db:
            health = await db.get(RouteHealth, second.health_key)
            health.cooldown_until = now() + timedelta(minutes=10)
            await db.commit()
        async with env.sessions() as db:
            assert not await finish_recovery(db, second, result=success())
            await db.commit()
        async with env.sessions() as db:
            health = await db.get(RouteHealth, second.health_key)
            assert health.tested_at is None
            assert health.probe_until is None
            assert health.cooldown_until > now()


async def test_revoked_administrator_and_bad_embedding_dimensions_never_certify(env):
    admin = await env.client()
    app, _ = chat_upstream()
    async with listening(app) as base:
        model, channels = await configure_chat(env, admin, base)
        lease = await claim(env, admin, model, channels[0], chat_body(channels[0]))
        async with env.sessions() as db:
            member = await db.get(Membership, admin.member.id)
            member.role = "member"
            await db.commit()
        async with env.sessions() as db:
            assert not await finish_recovery(db, lease, result=success())
            await db.commit()
    # A separate organization fixture is not needed: use a new administrator account.
    admin = await env.client()
    app, _ = chat_upstream()
    async with listening(app) as base:
        model, channel = await configure_retrieval(env, admin, base)
        model = await update(
            admin,
            model,
            retrieval={**model["retrieval"], "embedding_space": "fixture-v1"},
            bindings=[{**model["bindings"][0], "compatibility_key": "fixture-v1"}],
        )
        body = ChannelEmbeddingProbe(
            operation="embedding",
            version=channel["version"],
            id="upstream",
            input=["one"],
            dimensions=3,
        )
        lease = await claim(env, admin, model, channel, body)
        bad = success(
            operation="embedding", vectors=[VectorPreview(index=0, dimensions=2, values=[0.1, 0.2])]
        )
        async with env.sessions() as db:
            assert not await finish_recovery(db, lease, result=bad)
            await db.commit()


async def test_image_probe_must_match_fixed_model_parameters(env):
    admin = await env.client()
    app, _ = chat_upstream()
    async with listening(app) as base:
        env.provider.settings.llm_allowed_private_origins = [base]
        model = await configure_image(admin, base)
        channel_id = model["bindings"][0]["channel_id"]
        async with env.sessions() as db:
            channel = await db.get(ModelChannel, UUID(channel_id))
            version = channel.version
        channel = {"id": channel_id, "version": version}
        body = ChannelImageProbe(
            operation="image_generation",
            version=version,
            id="opaque/model",
            prompt="fixture",
            size=None,
            quality="low",
        )
        with pytest.raises(HTTPException) as wrong:
            await claim(env, admin, model, channel, body)
        assert wrong.value.status_code == 422


async def test_rerank_result_indices_must_reference_probed_documents(env):
    admin = await env.client()
    app, _ = chat_upstream()
    async with listening(app) as base:
        model, channel = await configure_retrieval(env, admin, base, kind="rerank")
        body = ChannelRerankProbe(
            operation="rerank",
            version=channel["version"],
            id="upstream",
            query="fixture",
            documents=["first", "second"],
            top_n=1,
        )
        lease = await claim(env, admin, model, channel, body)
        async with env.sessions() as db:
            assert not await finish_recovery(
                db,
                lease,
                result=success(
                    operation="rerank", ranks=[RankPreview(index=4, relevance_score=0.8)]
                ),
            )
            await db.commit()
        lease = await claim(env, admin, model, channel, body)
        async with env.sessions() as db:
            assert await finish_recovery(
                db,
                lease,
                result=success(
                    operation="rerank", ranks=[RankPreview(index=1, relevance_score=0.8)]
                ),
            )
            await db.commit()
