"""Supplier directory parsing and cache failures never invent model inventory."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.modules.model_gateway import ark_directory
from app.modules.model_gateway.ark_directory import PlanDirectory, parse_models


def document():
    rows = ["header", "chat", "vision", "image", "notes"]
    columns = ["category", "kind", "name"]
    zones = {
        "0": {"ops": [{"insert": "*", "attributes": {"aceTable": "rows cols"}}]},
        "rows": {"ops": [{"insert": {"id": row}} for row in rows]},
        "cols": {"ops": [{"insert": {"id": column}} for column in columns]},
    }
    cells = [
        ["分类", "领域", "模型名称"],
        ["模型", "文本生成（标准）", "source-chat.v1"],
        ["", "文本生成（进阶）", "source-vision (alias)\n注意\nother-model"],
        ["", "图片生成", "source-image"],
        ["", "Harness", "source-tool"],
    ]
    for row, values in zip(rows, cells, strict=True):
        for column, value in zip(columns, values, strict=True):
            zones[f"x{row}x{column}"] = {"ops": [{"insert": "*" + value + "\n"}]}
    return {
        "loaderData": {
            "docs/(libid)/(docid$)/page": {"curDoc": {"Content": json.dumps({"data": zones})}}
        }
    }


def html(payload):
    return "<script>window._ROUTER_DATA = " + json.dumps(payload) + "</script>"


def test_directory_only_reads_primary_names_from_text_support_rows():
    assert parse_models(html(document())) == ["source-chat.v1", "source-vision"]


@pytest.mark.parametrize("body", ["", "<html>upstream failed</html>", html({})])
def test_unrecognized_document_cannot_return_a_static_inventory(body):
    with pytest.raises((ValueError, KeyError)):
        parse_models(body)


@pytest.mark.asyncio
async def test_cached_directory_is_bounded_and_never_serves_an_expired_inventory(monkeypatch):
    fetch = AsyncMock(return_value=html(document()))
    monkeypatch.setattr(ark_directory, "fetch_document", fetch)
    clock = 1.0
    monkeypatch.setattr(ark_directory.time, "monotonic", lambda: clock)
    cache = PlanDirectory()
    assert await cache.get(None) == ["source-chat.v1", "source-vision"]
    models = await cache.get(None)
    models.clear()  # A caller must not mutate the shared directory.
    assert len(await cache.get(None)) == 2
    assert fetch.await_count == 1
    clock += 3601
    fetch.side_effect = ValueError("private supplier response")
    with pytest.raises(HTTPException) as error:
        await cache.get(None)
    assert error.value.status_code == 503
    assert "private" not in error.value.detail
    fetch.side_effect = None
    assert len(await cache.get(None)) == 2
    assert fetch.await_count == 3
