"""Pin each outbound connection to validated DNS results; no ambient proxies/cookies."""

import asyncio
import ipaddress
import json
import socket
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import urlsplit

import httpx2
from fastapi import HTTPException


def endpoint(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or len(value) > 2000
        or any(ord(c) < 33 for c in value)
    ):
        raise ValueError("地址须为完整 HTTP(S) 地址，不含账号、查询参数或片段")
    try:
        _ = url.port
    except ValueError as exc:
        raise ValueError("端口无效") from exc
    return value


def origin(value: str) -> str:
    p = urlsplit(value)
    return f"{p.scheme}://{p.hostname}:{p.port or (443 if p.scheme == 'https' else 80)}"


async def public_dns(hostname: str) -> list[str]:
    """Opt-in DoH, bootstrapped at a fixed TLS-verified resolver IP.

    Only the hostname is disclosed, never service paths, headers or credentials.
    No redirects, ambient proxies or fallback to system DNS on resolver failure.
    """

    async def query(client: httpx2.AsyncClient, record_type: str) -> list[str]:
        async with client.stream(
            "GET",
            "https://1.1.1.1/dns-query",
            params={"name": hostname, "type": record_type},
            headers={"accept": "application/dns-json"},
        ) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 64_000:
                    raise ValueError("DNS response too large")
            data = json.loads(body)
        if not isinstance(data, dict) or data.get("Status") != 0 or data.get("TC") is True:
            raise ValueError("DNS query failed")
        answers = data.get("Answer", [])
        if not isinstance(answers, list):
            raise ValueError("Invalid DNS answer")
        addresses = []
        for entry in answers:
            if not isinstance(entry, dict):
                raise ValueError("Invalid DNS record")
            if entry.get("type") in (1, 28):
                address = ipaddress.ip_address(entry["data"])
                if address.version != (4 if entry["type"] == 1 else 6):
                    raise ValueError("Invalid address family")
                addresses.append(str(address))
        return addresses

    try:
        async with asyncio.timeout(6):
            async with httpx2.AsyncClient(
                trust_env=False, follow_redirects=False, timeout=5
            ) as client:
                ipv4, ipv6 = await asyncio.gather(query(client, "A"), query(client, "AAAA"))
        if not ipv4 and not ipv6:
            raise ValueError("No DNS addresses")
        return list(dict.fromkeys(ipv4 + ipv6))
    except (httpx2.HTTPError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, "公网 DNS 解析失败，请检查服务域名或部署网络后重试") from exc


async def resolve(
    value: str,
    allowed_origins: list[str],
    *,
    dns: str = "system",
    dns_lookup: Callable[[str], Awaitable[list[str]]] = public_dns,
) -> str:
    try:
        endpoint(value)
    except ValueError as exc:
        raise HTTPException(422, "服务地址无效") from exc
    p = urlsplit(value)
    allowed = origin(value) in {origin(u) for u in allowed_origins}
    if p.scheme != "https" and not allowed:
        raise HTTPException(422, "远程服务须使用 HTTPS；内网 HTTP 地址需由部署人员显式放行")
    hostname = p.hostname or ""
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = [str(literal)]
    elif dns == "cloudflare" and not allowed:
        addresses = await dns_lookup(hostname)
    else:
        try:
            async with asyncio.timeout(6):
                entries = await asyncio.get_running_loop().getaddrinfo(
                    hostname,
                    p.port or (443 if p.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
        except (OSError, TimeoutError) as exc:
            raise HTTPException(422, "无法解析服务地址") from exc
        addresses = [str(e[4][0]) for e in entries]
    if not addresses:
        raise HTTPException(422, "无法解析服务地址")
    if not allowed and any(not ipaddress.ip_address(a).is_global for a in addresses):
        if literal is None:
            raise HTTPException(
                422,
                "服务域名解析到了非公网地址，可能受代理 Fake-IP 或内网 DNS 影响；"
                "请检查部署 DNS，真正的内网服务需显式放行",
            )
        raise HTTPException(422, "该非公网地址未被部署配置放行")
    return addresses[0]


class LimitedStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream, max_bytes: int = 4_000_000) -> None:
        self.stream = stream
        self.max_bytes = max_bytes

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        async for chunk in self.stream:
            total += len(chunk)
            if total > self.max_bytes:
                raise HTTPException(502, "上游响应超过大小限制")
            yield chunk

    async def aclose(self) -> None:
        await self.stream.aclose()


class PinnedTransport(httpx2.AsyncBaseTransport):
    def __init__(
        self,
        base: str,
        resolver: Callable[[str], Awaitable[str]],
        *,
        max_bytes: int = 4_000_000,
        on_send: Callable[[], None] | None = None,
    ) -> None:
        self.base = base
        self.resolver = resolver
        self.max_bytes = max_bytes
        self.on_send = on_send
        self.inner = httpx2.AsyncHTTPTransport(trust_env=False, retries=0)

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if origin(str(request.url)) != origin(self.base):
            raise HTTPException(422, "服务尝试连接未授权的来源")
        # SSE POST endpoint may contain protocol query parameters; never follow redirects.
        bare = str(request.url.copy_with(query=None, fragment=None))
        address = await self.resolver(bare)
        hostname = request.url.host
        request.headers["host"] = request.url.netloc.decode()
        request.extensions["sni_hostname"] = hostname
        request.url = request.url.copy_with(host=address)
        if self.on_send is not None:
            self.on_send()
        response = await self.inner.handle_async_request(request)
        if isinstance(response.stream, httpx2.AsyncByteStream):
            response.stream = LimitedStream(response.stream, self.max_bytes)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()
