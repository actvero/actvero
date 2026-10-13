"""Resolver and pinned-transport tests; no network, database or user credentials."""

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx2
import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.modules.mcp import network

pytestmark = pytest.mark.asyncio


def settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def mock_doh(monkeypatch, handler):
    original = httpx2.AsyncClient

    def client(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["follow_redirects"] is False
        return original(**kwargs, transport=httpx2.MockTransport(handler))

    monkeypatch.setattr(network.httpx2, "AsyncClient", client)


async def test_encrypted_dns_ignores_system_fake_ip_and_sends_hostname_only(monkeypatch):
    system = AsyncMock(side_effect=AssertionError("System resolver must not be used"))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", system)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "1.1.1.1"
        assert request.url.scheme == "https"
        assert request.url.params["name"] == "public.example"
        assert not request.headers.get("authorization")
        assert not request.headers.get("cookie")
        kind = request.url.params["type"]
        return httpx2.Response(
            200,
            json={
                "Status": 0,
                "Answer": [
                    {"type": 5, "data": "cdn.example"},
                    {
                        "type": 1 if kind == "A" else 28,
                        "data": "1.0.0.1" if kind == "A" else "2606:4700:4700::1111",
                    },
                ],
            },
        )

    mock_doh(monkeypatch, handler)
    assert (
        await network.resolve(
            "https://public.example/private-path", settings(mcp_public_dns="cloudflare")
        )
        == "1.0.0.1"
    )
    assert len(requests) == 2
    assert all("private-path" not in str(r.url) for r in requests)
    system.assert_not_called()


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "198.18.0.2",
        "::1",
        "fd00::1",
        "::ffff:127.0.0.1",
    ],
)
async def test_public_dns_cannot_allow_private_or_mixed_results(monkeypatch, address):
    monkeypatch.setattr(network, "public_dns", AsyncMock(return_value=["1.0.0.1", address]))
    with pytest.raises(HTTPException, match="非公网"):
        await network.resolve("https://public.example/mcp", settings(mcp_public_dns="cloudflare"))
    with pytest.raises(HTTPException, match="非公网"):
        literal = f"[{address}]" if ":" in address else address
        await network.resolve(f"https://{literal}/mcp", settings(mcp_public_dns="cloudflare"))


@pytest.mark.parametrize(
    "response",
    [
        {"Status": 3},
        {"Status": 2},
        {"Status": 0},
        {"Status": 0, "TC": True},
        {"Status": 0, "Answer": [{"type": 1, "data": "not-an-ip"}]},
        {"Status": 0, "Answer": [{"type": 1, "data": "::1"}]},
        {"Status": 0, "Answer": None},
        [],
    ],
)
async def test_dns_errors_fail_closed_without_system_fallback(monkeypatch, response):
    system = AsyncMock(side_effect=AssertionError("No fallback"))
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", system)
    mock_doh(monkeypatch, lambda _: httpx2.Response(200, json=response))
    with pytest.raises(HTTPException, match="公网 DNS 解析失败"):
        await network.resolve("https://public.example/mcp", settings(mcp_public_dns="cloudflare"))
    system.assert_not_called()


@pytest.mark.parametrize("mode", ["redirect", "oversize", "timeout", "invalid-json"])
async def test_resolver_transport_failures_are_bounded(monkeypatch, mode):
    def handler(request):
        if mode == "timeout":
            raise httpx2.ReadTimeout("timeout", request=request)
        if mode == "redirect":
            return httpx2.Response(302, headers={"location": "http://127.0.0.1"})
        return httpx2.Response(200, content=b"x" * (64001 if mode == "oversize" else 2))

    mock_doh(monkeypatch, handler)
    with pytest.raises(HTTPException, match="公网 DNS 解析失败"):
        await network.public_dns("public.example")


async def test_explicit_private_origins_use_system_dns_and_do_not_leak_names(monkeypatch):
    public = AsyncMock(side_effect=AssertionError("Do not send internal name to public DNS"))
    monkeypatch.setattr(network, "public_dns", public)
    system = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 80))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", system)
    config = settings(
        mcp_public_dns="cloudflare", mcp_allowed_private_origins=["http://intranet:80"]
    )
    assert await network.resolve("http://intranet/mcp", config) == "10.0.0.1"
    public.assert_not_called()
    with pytest.raises(HTTPException):
        await network.resolve("http://intranet:81/mcp", config)


async def test_default_system_mode_reports_fake_ip_without_external_dns(monkeypatch):
    # FastMCP may load deployment dotenv values in earlier integration tests. Test
    # the configuration default without inheriting that process-wide environment.
    monkeypatch.delenv("ACTVERO_MCP_PUBLIC_DNS", raising=False)
    monkeypatch.delenv("ACTVERO_MCP_ALLOWED_PRIVATE_ORIGINS", raising=False)
    public = AsyncMock()
    monkeypatch.setattr(network, "public_dns", public)
    system = AsyncMock(
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.2", 443))]
    )
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", system)
    config = settings()
    assert config.mcp_public_dns == "system" and not config.mcp_allowed_private_origins
    with pytest.raises(HTTPException, match="Fake-IP"):
        await network.resolve("https://public.example/mcp", config)
    system.assert_awaited_once()
    public.assert_not_called()


async def test_requests_pin_validated_ip_and_keep_tls_hostname_and_origin_guard(monkeypatch):
    dns = AsyncMock(side_effect=[["1.0.0.1"], ["127.0.0.1"]])
    monkeypatch.setattr(network, "public_dns", dns)
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "1.0.0.1"
        assert request.headers["host"] == "public.example"
        assert request.extensions["sni_hostname"] == "public.example"
        assert request.url.path == "/mcp"
        return httpx2.Response(200, json={"ok": True})

    transport = network.PinnedTransport(
        "https://public.example/mcp", settings(mcp_public_dns="cloudflare")
    )
    await transport.inner.aclose()
    transport.inner = httpx2.MockTransport(handler)
    async with httpx2.AsyncClient(transport=transport) as client:
        assert (await client.get("https://public.example/mcp")).status_code == 200
        with pytest.raises(HTTPException, match="非公网"):
            await client.get("https://public.example/mcp")
        with pytest.raises(HTTPException, match="未授权"):
            await client.get("https://other.example/mcp")
    assert len(requests) == 1


async def test_real_tls_uses_original_hostname_with_pinned_ip(monkeypatch, tmp_path):
    import ssl
    from datetime import UTC, datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "public.example")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("public.example")]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_file, key_file)
    seen_names = []
    server_context.set_servername_callback(lambda _socket, name, _context: seen_names.append(name))

    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0, ssl=server_context)
    original = asyncio.get_running_loop().getaddrinfo

    async def dns(host, port, **kwargs):
        return await original("127.0.0.1" if host == "public.example" else host, port, **kwargs)

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    base = f"https://public.example:{server.sockets[0].getsockname()[1]}"
    transport = network.PinnedTransport(base, settings(mcp_allowed_private_origins=[base]))
    await transport.inner.aclose()
    transport.inner = httpx2.AsyncHTTPTransport(
        verify=ssl.create_default_context(cafile=str(cert_file)), trust_env=False
    )
    try:
        async with httpx2.AsyncClient(transport=transport) as client:
            response = await client.get(base + "/mcp")
        assert response.text == "OK"
        assert seen_names == ["public.example"]
    finally:
        server.close()
        await server.wait_closed()
