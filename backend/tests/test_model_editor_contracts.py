"""Model editor changes preserve live permissions, prices and explicit bindings."""

from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from test_identity_access import env as identity_env
from test_llm_catalog import create as create_model
from test_llm_channels import create as create_channel

from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.member_catalog import available_models, member_page, public_page
from app.modules.llm.model_candidates import matches
from app.modules.llm.models import CatalogModel, ModelChannel
from app.modules.llm.reference_price_preview import ReferencePricePreviewInput, preview
from app.modules.llm.reference_quotes import QuoteSnapshot
from app.modules.members.service import BusinessActor
from app.modules.tenants.models import Tenant

env = identity_env
SNAPSHOT = {
    "provider": "example",
    "model_id": "upstream",
    "fetched_at": "2026-10-06T01:00:00Z",
    "currency": "USD",
    "unit": 1000000,
    "metric": "tokens",
    "raw_cost": {"input": "0.123456789012", "cache_write": "0.2", "tier": {"over": 128000}},
    "conditions": ["缓存写入时长未知", "按上下文阶梯计费"],
}


def test_matching_is_literal_and_case_sensitive():
    assert matches("vendor/qwen-latest", "qwen", "contains")
    assert matches("qwen-latest", "qwen", "prefix")
    assert matches("vendor/qwen", "qwen", "suffix")
    assert matches("qwen", "qwen", "exact")
    assert not matches("Qwen", "qwen", "exact")
    assert not matches("qwen", "*", "contains")
    assert not matches("a1b", "a_b", "exact")
    assert not matches("aaa", "a%", "prefix")


@pytest.mark.parametrize(
    "change",
    [
        {"raw_cost": {"rate": float("inf")}},
        {"fetched_at": "2026-10-06T01:00:00"},
        {"unit": 0},
        {"unit": True},
        {"source_url": "https://user:secret@example.com"},
        {"source_url": "javascript:alert(1)"},
        {"conditions": ["x" * 1001]},
        {"raw_cost": {"a": "x" * 32769}},
    ],
)
def test_reference_snapshot_rejects_invalid_or_unbounded_payload(change):
    with pytest.raises(ValidationError):
        QuoteSnapshot.model_validate(SNAPSHOT | change)


def test_snapshot_does_not_create_a_price_or_interface():
    config = CatalogInput.model_validate(
        {
            "name": "仅登记",
            "slug": "draft",
            "operations": [],
            "quote_snapshots": [SNAPSHOT],
        }
    )
    assert config.operations == [] and not config.access.enabled
    assert config.budget_price is None
    assert config.quote_snapshots[0].raw_cost["cache_write"] == "0.2"
    with pytest.raises(ValidationError):
        CatalogInput.model_validate(
            {"name": "draft", "slug": "draft", "quote_snapshots": [SNAPSHOT] * 11}
        )


def test_currency_preview_normalizes_units_and_preserves_unknown_rates():
    body = ReferencePricePreviewInput.model_validate(
        {
            "price": {"currency": "USD", "unit": 1000, "input": "0.002", "output": None},
            "target_currency": "CNY",
            "fx_rate": "7.123456789012345",
            "fx_date": "2026-10-06",
        }
    )
    result = preview(body)
    assert result.price.unit == 1000000 and result.price.currency == "CNY"
    assert result.price.input == Decimal("14.246913578025")
    assert result.price.output is None and result.price.cache_write_5m is None
    assert len(result.rounding_notes) == 1
    assert result.fx_rate == body.fx_rate
    body.fx_rate = "0.000000000000001"
    with pytest.raises(ValueError, match="零价"):
        preview(body)


@pytest.mark.asyncio
async def test_candidates_scope_permissions_paging_and_no_automatic_binding(env):
    admin = await env.client()
    current = await create_channel(admin, models=[{"id": f"qwen-{i:03d}"} for i in range(55)])
    archived = await create_channel(admin, name="归档", models=[{"id": "qwen-hidden"}])
    await admin.api.put(
        f"/api/v1/llm/channels/{archived['id']}/archive", json={"version": 1, "archived": True}
    )
    await create_channel(
        admin, name="非对话", declared_apis=["embeddings"], models=[{"id": "qwen-vector"}]
    )
    async with env.sessions() as db:
        # Match SaaS migration in this disposable test schema only.
        await db.execute(text("ALTER TABLE tenants DROP CONSTRAINT tenants_instance_slot_key"))
        foreign = Tenant(name="其他组织")
        db.add(foreign)
        await db.flush()
        db.add(
            ModelChannel(
                tenant_id=foreign.id,
                provider="openai-compatible",
                name="不应泄露",
                auth_mode="none",
                declared_apis=["chat_completions"],
                base_url="https://example.com/v1",
                models=[{"id": "qwen-secret"}],
            )
        )
        await db.commit()
    url = "/api/v1/llm/model-candidates?kind=chat&q=qwen&match=prefix"
    result = await admin.api.get(url)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["total"] == 55 and len(data["items"]) == 50
    assert all(item["channel_id"] == current["id"] for item in data["items"])
    page2 = (await admin.api.get(url + "&page=2")).json()
    assert len(page2["items"]) == 5
    assert not (
        set(item["upstream_id"] for item in data["items"])
        & set(item["upstream_id"] for item in page2["items"])
    )
    assert (await admin.api.get(url.replace("q=qwen", "q=Qwen"))).json()["total"] == 0
    assert (await admin.api.get(url + "&page=0")).status_code == 422
    assert "sealed_key" not in result.text and "test-secret" not in result.text
    member = await env.client(role="member", tenant=admin.tenant)
    assert (await member.api.get(url)).status_code == 403
    async with env.sessions() as db:
        assert list(await db.scalars(select(CatalogModel))) == []


@pytest.mark.asyncio
async def test_snapshot_and_order_roundtrip_legacy_update_preserves_extensions(env):
    admin = await env.client()
    row = await create_model(admin, quote_snapshots=[SNAPSHOT], display_order=42)
    path = "/api/v1/llm/models/" + row["id"]
    result = await admin.api.put(
        path, json={"version": 1, "slug": row["slug"], "name": "旧客户端修改"}
    )
    assert result.status_code == 200, result.text
    saved = result.json()
    assert saved["display_order"] == 42 and saved["quote_snapshots"] == row["quote_snapshots"]
    assert saved["budget_price"] is None and saved["bindings"] == []
    empty = await admin.api.put(
        path,
        json={
            "version": 2,
            "slug": row["slug"],
            "name": saved["name"],
            "display_order": 0,
            "quote_snapshots": [],
        },
    )
    assert empty.status_code == 200
    assert empty.json()["quote_snapshots"] == [] and empty.json()["display_order"] == 0
    for value in [-1, True, 1.5, 1000001]:
        invalid = await admin.api.put(
            path,
            json={"version": 3, "slug": row["slug"], "name": saved["name"], "display_order": value},
        )
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_member_and_public_catalog_share_stable_order_without_reference_leak(env):
    admin = await env.client()
    channel = await create_channel(admin, models=[{"id": "upstream"}])
    common = {
        "context_window": 128000,
        "max_output": 4096,
        "access": {
            "enabled": True,
            "audience": "organization",
            "channel_id": channel["id"],
            "upstream_id": "upstream",
        },
        "bindings": [{"channel_id": channel["id"], "upstream_id": "upstream", "enabled": True}],
        "quote_snapshots": [SNAPSHOT],
    }
    for slug, order in [("z-last", 0), ("b-first", 100), ("a-first", 100), ("c-middle", 20)]:
        await create_model(admin, **(common | {"slug": slug, "display_order": order}))
    await create_model(admin, slug="hidden", display_order=1000, operations=[])
    member = await env.client(role="member", tenant=admin.tenant)
    actor = BusinessActor(member.user, member.member, member.tenant)
    async with env.sessions() as db:
        public = await public_page(db, actor, 1)
        account = await member_page(db, actor)
        assert [row.id for row in public.data] == ["a-first", "b-first", "c-middle", "z-last"]
        assert [row.slug for row in account.items] == [row.id for row in public.data]
        assert [row.display_order for row in public.data] == [100, 100, 20, 0]
        serialized = public.model_dump_json() + account.model_dump_json()
        assert "raw_cost" not in serialized and "quote_snapshots" not in serialized
        assert "channel_id" not in serialized and "upstream_id" not in serialized
        rows = await available_models(db, actor)
        assert len(rows) == 4


@pytest.mark.asyncio
async def test_reference_conversion_requires_admin_csrf_and_does_not_persist_prices(env):
    admin = await env.client()
    body = {
        "price": {"currency": "USD", "input": "0.15", "output": "0.47"},
        "target_currency": "CNY",
        "fx_rate": "7",
        "fx_date": "2026-10-06",
    }
    path = "/api/v1/llm/reference-price-preview"
    result = await admin.api.post(path, json=body)
    assert result.status_code == 200, result.text
    assert Decimal(result.json()["price"]["input"]) == Decimal("1.05")
    assert (
        await admin.api.post(path, json=body, headers={"x-csrf-token": "bad"})
    ).status_code == 403
    member = await env.client(role="member", tenant=admin.tenant)
    assert (await member.api.post(path, json=body)).status_code == 403
    async with env.sessions() as db:
        assert list(await db.scalars(select(CatalogModel))) == []
