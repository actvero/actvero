"""Pure member catalog and dual-status projections; DB authorization has separate API tests."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.llm import member_catalog
from app.modules.llm.catalog_schemas import ModelCapabilities, RetrievalOptions
from app.modules.llm.inference_schemas import PublicModel, PublicOperation
from app.modules.llm.settlement_router import public_usage, settlement_view


def model(slug: str, kinds: tuple[str, ...] = ("chat",)) -> tuple:
    operations = [
        PublicOperation(
            kind=kind,
            limits=RetrievalOptions(),
            capabilities=ModelCapabilities(),
            context_window=128000,
            max_output=4096,
            reasoning_options=[],
            point_rates={"input": "1", "output": "2"},
            metric="tokens",
        )
        for kind in kinds
    ]
    row_id = uuid4()
    return (
        row_id,
        PublicModel(
            resource=f"llm:{row_id}",
            created=1,
            id=slug,
            name=f"可用 {slug}",
            operations=operations,
            **operations[0].model_dump(),
        ),
        {kind: "ready" for kind in kinds},
    )


@pytest.mark.asyncio
async def test_member_page_filters_before_paging_and_reuses_public_models(monkeypatch):
    available = [model(f"visible-{index:02d}") for index in range(25)]
    available.append(model("vector-one", ("embedding",)))

    async def rows(*_args):
        return available

    monkeypatch.setattr(member_catalog, "available_models", rows)
    public = await member_catalog.public_page(object(), object(), 2)
    assert len(public.data) == 6 and public.data[0].id == "visible-20"

    filtered = await member_catalog.member_page(
        object(), object(), q="VECTOR", operation="embedding", page=1
    )
    assert filtered.total == 1 and filtered.page_size == 20 and not filtered.has_more
    item = filtered.items[0]
    assert item.slug == "vector-one" and str(item.id) in item.resource
    assert [operation.kind for operation in item.operations] == ["embedding"]
    assert item.operations[0].point_price_status == "ready"
    assert item.operations[0].endpoint.path == "/api/llm/v1/embeddings"
    assert item.operations[0].endpoint.example == {"model": "vector-one", "input": "示例文本"}
    serialized = filtered.model_dump_json()
    assert "api_key" not in serialized and "upstream_id" not in serialized
    assert "channel_id" not in serialized and "procurement" not in serialized


@pytest.mark.asyncio
async def test_member_page_shows_missing_price_status_without_fake_points(monkeypatch):
    available = [model("unpriced")]
    row_id, public, _ = available[0]
    public.operations[0].point_rates = {}
    available[0] = (row_id, public, {"chat": "no_price"})

    async def rows(*_args):
        return available

    monkeypatch.setattr(member_catalog, "available_models", rows)
    result = await member_catalog.member_page(object(), object())
    assert result.items[0].operations[0].point_price_status == "no_price"
    assert result.items[0].operations[0].point_rates == {}


def test_public_usage_exposes_only_canonical_numeric_meter_fields():
    assert public_usage(
        {
            "input_tokens": 42,
            "output_tokens": None,
            "cache_read_tokens": False,
            "image_count": 0,
            "source": "upstream",
            "prompt": "secret",
            "provider_body": {"credential": "secret"},
        }
    ) == {"input_tokens": 42, "image_count": 0, "source": "upstream"}


def test_member_usage_keeps_old_status_and_independent_result_axis():
    call = SimpleNamespace(
        kind="chat",
        status="succeeded",
        error_code=None,
        termination_code="access_changed",
    )
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid4(),
        member_id=uuid4(),
        price={"metric": "tokens"},
        status="review",
        version=2,
        amount=None,
        reserved_amount=Decimal("0.25"),
        ratio=Decimal("100"),
        usage={"input_tokens": 8, "prompt": "hidden"},
        created_at=now,
        settled_at=None,
        reason="Administrator note should not leak",
    )
    user = SimpleNamespace(name="Current Member")
    catalog = SimpleNamespace(name="Shared Model")
    result = settlement_view(row, user, catalog, call, public=True)
    assert result.status == "review" and result.settlement_status == "review"
    assert result.result_status == "interrupted" and result.terminal_reason == "access_changed"
    assert result.reserved_points == "25" and result.points is None
    assert result.usage == {"input_tokens": 8} and result.reason == ""
