"""Real quota migration and automatic capability resolution, without provider calls."""

import importlib.util
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from test_identity_access import env as identity_env
from test_quota_accounting_audit import entry, quota, setup
from test_quota_policies import hours

from app.modules.llm.models import QuotaClock, UsageSettlement
from app.modules.model_gateway.capabilities import lookup, resolve
from app.modules.quota.models import QuotaPolicy

env = identity_env


def test_real_mapping_uses_exact_capabilities_and_does_not_guess_unknown_models():
    channels = [
        {
            "type": 43,
            "models": "team",
            "status": 1,
            "group": "default",
            "model_mapping": '{"team":"deepseek-flash"}',
        }
    ]
    found = resolve("team", "default", channels)
    assert found["status"] == "resolved"
    assert found["source"]["model"] == "deepseek-flash"
    assert found["reasoning_options"][0]["values"] == ["none", "low", "high", "max"]
    assert found["chat_policy"]["default_reasoning_effort"] == "high"
    assert found["chat_policy"]["default_max_output"] < found["max_output"]
    assert resolve("team", "other", channels)["status"] == "unresolved"
    assert lookup("openai", "made-up-gpt-next") is None
    assert lookup("openai", "gpt-5")["reasoning_options"][0]["values"] == [
        "minimal",
        "low",
        "medium",
        "high",
    ]
    channels.append({**channels[0], "model_mapping": '{"team":"deepseek-v4-pro"}'})
    assert resolve("team", "default", channels)["status"] == "conflict"


@pytest.mark.asyncio
async def test_calendar_migration_preserves_current_spend_holds_and_duplicate_windows(
    env, monkeypatch
):
    stamp = datetime.now(UTC)
    admin, policy, model, channels = await setup(env, [hours("800", 168)])
    settled = await entry(
        env, admin, model, channels, stamp - timedelta(minutes=30), status="settled", amount="0.2"
    )
    held = await entry(env, admin, model, channels, stamp - timedelta(minutes=20), amount="0.1")
    old_start = stamp - timedelta(hours=2)
    async with env.sessions() as db:
        row = await db.get(QuotaPolicy, UUID(policy["id"]))
        row.rules = [
            hours("800", 168),
            {
                "kind": "calendar_week",
                "points": "700",
                "timezone": "America/New_York",
                "week_start": 0,
            },
        ]
        db.add(
            QuotaClock(
                member_id=admin.member.id,
                tenant_id=admin.tenant.id,
                windows={"168": {"start": old_start.isoformat()}},
            )
        )
        await db.commit()
        before = [(await db.get(UsageSettlement, id)).policy_snapshot for id in (settled, held)]
        connection = await db.connection()

        # Exercise this historical migration against its original policy columns.
        await db.execute(
            text("ALTER TABLE quota_policies ADD COLUMN priority integer NOT NULL DEFAULT 0")
        )
        await db.execute(
            text(
                "ALTER TABLE quota_policies ADD COLUMN member_ids "
                "jsonb NOT NULL DEFAULT '[]'::jsonb"
            )
        )

        def migrate(sync):
            spec = importlib.util.spec_from_file_location(
                "quota_cycles", Path("migrations/versions/119n_fixed_quota_cycles.py")
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.op = Operations(MigrationContext.configure(sync))
            module.upgrade()

        await connection.run_sync(migrate)
        await db.commit()
        db.expire_all()
        migrated = await db.get(QuotaPolicy, UUID(policy["id"]))
        assert migrated.rules == [hours("700", 168)]
        assert migrated.version == policy["version"] + 1
        assert before == [
            (await db.get(UsageSettlement, id)).policy_snapshot for id in (settled, held)
        ]
        saved = (await db.get(QuotaClock, admin.member.id)).windows["168"]
    local = stamp.astimezone(ZoneInfo("America/New_York"))
    week_start = datetime.combine(
        local.date() - timedelta(days=local.weekday()), time(), local.tzinfo
    ).astimezone(UTC)
    assert datetime.fromisoformat(saved["start"]) == min(week_start, old_start)
    result = (await quota(env, admin, monkeypatch, stamp, activate=True))[0]
    assert result["remaining"] == "670"
    assert result["used"] == "20" and result["reserved"] == "10"
    end = datetime.fromisoformat(saved["end"])
    assert (await quota(env, admin, monkeypatch, end))[0]["started_at"] is None
    next_window = (await quota(env, admin, monkeypatch, end + timedelta(hours=1), activate=True))[0]
    assert datetime.fromisoformat(next_window["resets_at"]) - datetime.fromisoformat(
        next_window["started_at"]
    ) == timedelta(hours=168)


@pytest.mark.asyncio
async def test_new_model_requires_no_manual_parameters_and_alias_updates_refresh_catalog(
    env, monkeypatch
):
    from llm_billing_helpers import billing
    from pydantic import SecretStr
    from test_model_gateway import bind

    from app.modules.model_gateway import client

    admin = await env.client()
    bind(env, admin)
    connection = env.provider.settings.newapi_connections[0]
    connection.relay_key, connection.relay_token_id = SecretStr("fixture-relay"), 51
    await billing(admin)
    route = {
        "type": 43,
        "models": "team",
        "status": 1,
        "group": "default",
        "model_mapping": {"team": "deepseek-flash"},
    }

    async def native(request, tenant, method, path, **kwargs):
        if path == "/api/channel/":
            return {"items": [route], "total": 1}
        if path == "/api/option/model_pricing":
            return {"entries": [{"model_name": "team", "effective": {"ModelRatio": 1}}]}
        raise AssertionError(path)

    monkeypatch.setattr(client, "call", native)
    saved = await admin.api.put(
        "/api/v1/model-gateway/publication",
        json={"model_name": "team", "name": "Team", "enabled": True},
    )
    assert saved.status_code == 200, saved.text
    data = saved.json()["data"]
    assert data["capability_mode"] == "auto"
    assert data["context_window"] == 1000000
    assert data["chat_policy"]["default_reasoning_effort"] == "high"
    page = await admin.api.get("/api/v1/account/llm/models")
    assert page.status_code == 200, page.text
    assert page.json()["items"][0]["operations"][0]["capabilities"]["vision"] == "supported"
    assert page.json()["items"][0]["operations"][0]["input_modalities"] == ["text", "image"]
    image_input = page.json()["items"][0]["operations"][0]["image_input"]
    assert image_input == {
        "max_image_bytes": 1024 * 1024,
        "max_total_bytes": 8 * 1024 * 1024,
        "max_images": 32,
        "target_pixels": 2048 * 2048,
    }
    route["model_mapping"] = {"team": "deepseek-v4-pro"}
    changed = (await admin.api.get("/api/v1/account/llm/models")).json()["items"][0]["operations"][
        0
    ]
    assert changed["capability_source"]["model"] == "deepseek-v4-pro"
    assert changed["capabilities"]["vision"] == "unsupported"
    assert changed["input_modalities"] == ["text"]
    assert changed["image_input"] is None
    route["model_mapping"] = {"team": "unknown-model"}
    assert (await admin.api.get("/api/v1/account/llm/models")).json()["items"] == []


def test_multimodal_reference_only_advertises_current_chat_transport():
    flash = lookup("deepseek", "deepseek-flash")
    pro = lookup("deepseek", "deepseek-v4-pro")
    assert flash["input_modalities"] == ["text", "image"]
    assert pro["input_modalities"] == ["text"]
    assert flash["output_modalities"] == ["text"]
    assert flash["capabilities"]["tools"] == "supported"
    assert flash["chat_policy"]["default_max_output"] == 8192
    gemini = lookup("google", "gemini-2.5-pro")
    assert gemini["input_modalities"] == ["text", "image"]


def test_missing_feature_evidence_remains_unknown_and_does_not_erase_core_profile(monkeypatch):
    from app.modules.model_gateway import capabilities, feature_reference

    base = {
        "id": "shared",
        "context_window": 1000,
        "max_output": 100,
        "reasoning": False,
        "input": ["text"],
        "thinking": {},
    }
    monkeypatch.setattr(
        capabilities,
        "reference",
        lambda: [
            {**base, "provider": "openai"},
            {**base, "provider": "azure"},
        ],
    )
    monkeypatch.setattr(
        feature_reference,
        "reference",
        lambda: {
            "shared": {"supports_function_calling": True},
            "azure/shared": {"supports_function_calling": False},
        },
    )
    explicit = lookup("azure", "shared")
    assert explicit["capabilities"]["tools"] == "unsupported"
    assert explicit["capabilities"]["streaming"] == "unknown"
    assert explicit["capabilities"]["structured_output"] == "unknown"
    ambiguous = lookup(None, "shared")
    assert ambiguous["context_window"] == 1000
    assert ambiguous["capabilities"]["tools"] == "unknown"
