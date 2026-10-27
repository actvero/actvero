"""Expose actionable channel test failures without exposing upstream responses."""

from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from fastapi import HTTPException, Request

from app.modules.model_gateway import client

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("code", list(client.CHANNEL_TEST_ERRORS))
async def test_channel_test_only_translates_known_codes(monkeypatch, code):
    response = httpx2.Response(
        200,
        json={
            "success": False,
            "error_code": code,
            "message": "Bearer supplier-secret request-body-private",
            "data": {"key": "management-secret"},
        },
    )
    send = AsyncMock(return_value=response)
    monkeypatch.setattr(client, "send", send)
    with pytest.raises(HTTPException) as error:
        await client.call(Request({"type": "http"}), uuid4(), "GET", "/api/channel/test/1")
    assert error.value.status_code == 502
    assert error.value.detail == client.CHANNEL_TEST_ERRORS[code]
    assert "secret" not in error.value.detail
    assert "保存" not in error.value.detail
    assert send.await_count == 1


@pytest.mark.parametrize("code", [None, "supplier-secret", {"key": "secret"}, ["secret"]])
async def test_channel_test_unknown_error_codes_stay_private(monkeypatch, code):
    monkeypatch.setattr(
        client,
        "send",
        AsyncMock(
            return_value=httpx2.Response(
                200, json={"success": False, "error_code": code, "message": "private-secret"}
            )
        ),
    )
    with pytest.raises(HTTPException) as error:
        await client.call(Request({"type": "http"}), uuid4(), "GET", "/api/channel/test/1")
    assert error.value.detail == "渠道测试失败，请检查渠道地址、密钥、模型和计费配置"


@pytest.mark.parametrize("method", ["GET", "PUT"])
async def test_other_operations_keep_read_and_write_failures_distinct(monkeypatch, method):
    monkeypatch.setattr(
        client,
        "send",
        AsyncMock(
            return_value=httpx2.Response(
                200,
                json={"success": False, "error_code": "model_price_error", "message": "secret"},
            )
        ),
    )
    with pytest.raises(HTTPException) as error:
        await client.call(Request({"type": "http"}), uuid4(), method, "/api/channel/")
    assert "secret" not in error.value.detail
    assert ("保存" in error.value.detail) == (method == "PUT")


async def test_successful_channel_test_still_filters_native_response(monkeypatch):
    monkeypatch.setattr(
        client,
        "send",
        AsyncMock(
            return_value=httpx2.Response(
                200, json={"success": True, "time": 0.5, "message": "private-secret"}
            )
        ),
    )
    assert await client.call(Request({"type": "http"}), uuid4(), "GET", "/api/channel/test/1") == {
        "time": 0.5
    }
