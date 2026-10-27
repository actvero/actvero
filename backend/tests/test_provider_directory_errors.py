"""Directory failures use safe, actionable categories without external requests."""

import ssl

import httpx2
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.core.outbound import PinnedTransport
from app.modules.llm.providers import openai_compatible

pytestmark = pytest.mark.asyncio
SECRET = "private-catalog-key"


def _raise_failure(kind: str) -> None:
    if kind in {"certificate", "tls_eof"}:
        cause = (
            ssl.SSLCertVerificationError("certificate rejected: " + SECRET)
            if kind == "certificate"
            else ssl.SSLEOFError("TLS peer closed: " + SECRET)
        )
        try:
            raise cause
        except ssl.SSLError as error:
            raise httpx2.ConnectError("request to sensitive.example: " + SECRET) from error
    if kind == "reset":
        try:
            raise ConnectionResetError("connection reset: " + SECRET)
        except ConnectionResetError as error:
            raise httpx2.ReadError("read failed: " + SECRET) from error
    errors: dict[str, type[httpx2.HTTPError]] = {
        "connect": httpx2.ConnectError,
        "connect_timeout": httpx2.ConnectTimeout,
        "read_timeout": httpx2.ReadTimeout,
        "other_timeout": httpx2.PoolTimeout,
        "other_http": httpx2.RemoteProtocolError,
    }
    raise errors[kind]("request to sensitive.example: " + SECRET)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("certificate", "TLS 证书验证失败"),
        ("tls_eof", "TLS 握手或连接中断"),
        ("reset", "连接失败或中断"),
        ("connect", "连接失败或中断"),
        ("connect_timeout", "连接模型目录超时"),
        ("read_timeout", "等待模型目录响应超时"),
        ("other_timeout", "读取模型目录超时"),
        ("other_http", "无法读取模型目录"),
    ],
)
async def test_directory_transport_error_categories(monkeypatch, kind: str, expected: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["authorization"] == "Bearer " + SECRET
        _raise_failure(kind)

    class LocalPinnedTransport(PinnedTransport):
        def __init__(self, base, resolver):
            super().__init__(base, resolver)

            async def local_address(_url):
                return "127.0.0.1"

            self.resolver = local_address
            self.inner = httpx2.MockTransport(handler)

    monkeypatch.setattr(openai_compatible, "PinnedTransport", LocalPinnedTransport)
    with pytest.raises(HTTPException) as failure:
        await openai_compatible.OpenAICompatible().list_models(
            "https://sensitive.example/v1",
            SECRET,
            5,
            Settings(_env_file=None),
        )
    assert failure.value.status_code == 502
    assert expected in failure.value.detail
    assert SECRET not in failure.value.detail
    assert "sensitive.example" not in failure.value.detail


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, "检查 API Key"),
        (403, "检查账号权限"),
        (404, "接口返回 404"),
        (429, "稍后重试"),
        (503, "HTTP 503"),
    ],
)
async def test_directory_http_status_stays_sanitized(
    monkeypatch, status: int, expected: str
) -> None:
    class LocalPinnedTransport(PinnedTransport):
        def __init__(self, base, resolver):
            super().__init__(base, resolver)

            async def local_address(_url):
                return "127.0.0.1"

            self.resolver = local_address
            self.inner = httpx2.MockTransport(
                lambda _request: httpx2.Response(status, text="private response: " + SECRET)
            )

    monkeypatch.setattr(openai_compatible, "PinnedTransport", LocalPinnedTransport)
    with pytest.raises(HTTPException) as failure:
        await openai_compatible.OpenAICompatible().list_models(
            "https://sensitive.example/v1",
            SECRET,
            5,
            Settings(_env_file=None),
        )
    assert failure.value.status_code == 502
    assert expected in failure.value.detail
    assert SECRET not in failure.value.detail
