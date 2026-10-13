"""Stable, disclosed MCP revisions; never hash credentials into a client-visible proof."""

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp.models import McpContent, McpService
from app.modules.mcp.service import definition_hash

KINDS = ("tools", "prompts", "resources", "templates")


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def contract(entry: dict[str, Any], protocol: str) -> str:
    return digest({"protocol": protocol, "definition": definition_hash(entry["definition"])})


def behavior(entry: dict[str, Any], source_body: str | None = None) -> str:
    definition = entry["definition"]
    return digest(
        {
            "description": entry.get("description", ""),
            "title": definition.get("title"),
            "annotations": definition.get("annotations"),
            "source_body": source_body,
        }
    )


def display(service: McpService) -> str:
    return digest(
        {
            "name": service.name,
            "display_name": service.display_name,
            "description": service.description,
            "icon": service.icon,
            "examples": service.examples,
        }
    )


def connection(service: McpService) -> str:
    return digest(
        {
            "transport": service.transport,
            "url": service.url,
            "auth_mode": service.auth_mode,
            "credential_fields": [
                {k: v for k, v in field.items() if k != "label"}
                for field in service.credential_fields
            ],
            "oauth": service.oauth,
        }
    )


def authorization(service: McpService, entries: list[dict[str, Any]], member_id: str) -> str:
    return digest(
        {
            "enabled": service.enabled,
            "audience": service.audience,
            "member_in_scope": service.audience == "organization"
            or member_id in service.member_ids,
            "capabilities": sorted(
                (entry["kind"], entry["key"], entry["contract_revision"])
                for entry in entries
                if entry["enabled"]
            ),
        }
    )


async def source_body(db: AsyncSession, service: McpService, entry: dict[str, Any]) -> str | None:
    """Built-in text is available locally; external prompt/resource output is not."""
    if service.transport != "builtin" or entry["kind"] not in {"prompts", "resources"}:
        return None
    rows = (await db.scalars(select(McpContent).where(McpContent.service_id == service.id))).all()
    for row in rows:
        key = row.name if row.kind == "prompts" else f"actvero://resources/{row.id}"
        if row.kind == entry["kind"] and key == entry["key"]:
            return row.body
    return None
