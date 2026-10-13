"""Short-lived MCP clients: no shared sessions, headers, token store or catalog cache."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx2
from fastapi import HTTPException
from fastmcp import Client, FastMCP
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
from fastmcp.prompts import Prompt
from fastmcp.prompts.base import PromptArgument
from fastmcp.resources import TextResource
from pydantic import AnyUrl

from app.core.config import Settings
from app.modules.mcp.models import McpContent, McpService
from app.modules.mcp.network import client_factory, resolve
from app.modules.mcp.schemas import ConnectionOptions


class StoredPrompt(Prompt):
    body: str

    async def render(self, arguments: dict[str, Any] | None = None) -> str:
        values = arguments or {}
        return re.sub(r"\{\{(\w+)\}\}", lambda m: str(values[m[1]]), self.body)


def builtin(contents: list[McpContent]) -> FastMCP:
    server = FastMCP("Actvero 内置内容")
    for item in contents:
        if item.kind == "prompts":
            server.add_prompt(
                StoredPrompt(
                    name=item.name,
                    description=item.description,
                    body=item.body,
                    arguments=[PromptArgument(name=a, required=True) for a in item.arguments],
                )
            )
        else:
            server.add_resource(
                TextResource(
                    name=item.name,
                    description=item.description,
                    uri=AnyUrl(f"actvero://resources/{item.id}"),
                    mime_type=item.mime_type,
                    text=item.body,
                )
            )
    return server


@asynccontextmanager
async def connect(
    service: McpService, settings: Settings, headers: dict[str, str], contents: list[McpContent]
) -> AsyncIterator[Client[Any]]:
    options = ConnectionOptions.model_validate(service.connection_options or {})
    if service.transport == "builtin":
        transport: Any = builtin(contents)
    else:
        await resolve(service.url, settings)
        cls = SSETransport if service.transport == "sse" else StreamableHttpTransport
        transport = cls(
            service.url,
            headers=headers,
            httpx_client_factory=client_factory(
                service.url,
                settings,
                httpx2.Timeout(options.total_timeout, connect=options.connect_timeout),
            ),
        )
    # Explicit legacy negotiation is the tested compatibility baseline for this release.
    async with asyncio.timeout(options.total_timeout):
        async with Client(
            transport,
            timeout=options.request_timeout,
            init_timeout=options.connect_timeout,
            mode="legacy",
            cache=False,
        ) as client:
            yield client


async def discover(client: Client[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    capabilities = client.server_capabilities
    operations = [
        ("tools", client.list_tools_mcp, "tools", capabilities and capabilities.tools),
        ("prompts", client.list_prompts_mcp, "prompts", capabilities and capabilities.prompts),
        (
            "resources",
            client.list_resources_mcp,
            "resources",
            capabilities and capabilities.resources,
        ),
        (
            "templates",
            client.list_resource_templates_mcp,
            "resource_templates",
            capabilities and capabilities.resources,
        ),
    ]
    for kind, operation, attr, supported in operations:
        if supported is None:
            continue
        cursor: str | None = None
        seen: set[str] = set()
        for _ in range(50):
            page = await operation(cursor=cursor)
            for entry in getattr(page, attr):
                definition = entry.model_dump(mode="json", by_alias=True, exclude_none=True)
                key = str(
                    definition.get("uriTemplate") or definition.get("uri") or definition["name"]
                )
                if len(key) > 2000:
                    raise HTTPException(502, "服务返回的能力标识过长")
                result.append(
                    {
                        "kind": kind,
                        "key": key,
                        "name": definition.get("name", key),
                        "description": definition.get("description", ""),
                        "definition": definition,
                    }
                )
            cursor = page.next_cursor
            if not cursor:
                break
            if cursor in seen or len(result) > 2000:
                raise HTTPException(502, "能力目录超过限制或分页游标重复")
            seen.add(cursor)
        else:
            raise HTTPException(502, "能力目录分页超过限制")
    if len(result) > 2000 or len(json.dumps(result)) > 2_000_000:
        raise HTTPException(502, "能力目录过大")
    if len({(c["kind"], c["key"]) for c in result}) != len(result):
        raise HTTPException(502, "服务返回重复能力标识")
    return result


async def call_tool(
    client: Client[Any], service: McpService, name: str, arguments: dict[str, Any]
) -> Any:
    options = ConnectionOptions.model_validate(service.connection_options or {})
    async with asyncio.timeout(options.request_timeout) as idle:

        async def progress(progress: float, total: float | None, message: str | None) -> None:
            if options.reset_on_progress:
                idle.reschedule(asyncio.get_running_loop().time() + options.request_timeout)

        return await client.call_tool_mcp(
            name, arguments, progress_handler=progress, timeout=options.total_timeout
        )
