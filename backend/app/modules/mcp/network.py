"""MCP-specific policy over the shared DNS-pinned outbound transport."""

from typing import Any

import httpx2

from app.core.config import Settings
from app.core.outbound import PinnedTransport as OutboundTransport
from app.core.outbound import origin, public_dns  # noqa: F401 (compatibility exports)
from app.core.outbound import resolve as resolve_endpoint


async def resolve(value: str, settings: Settings) -> str:
    return await resolve_endpoint(
        value,
        settings.mcp_allowed_private_origins,
        dns=settings.mcp_public_dns,
        dns_lookup=public_dns,
    )


class PinnedTransport(OutboundTransport):
    def __init__(self, base: str, settings: Settings) -> None:
        super().__init__(base, lambda value: resolve(value, settings))


def client_factory(base: str, settings: Settings, timeout: Any = 20) -> Any:
    def factory(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.pop("follow_redirects", None)
        kwargs.pop("timeout", None)
        return httpx2.AsyncClient(
            **kwargs,
            transport=PinnedTransport(base, settings),
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        )

    return factory
