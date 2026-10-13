"""Immutable hashes of selected tool schemas, separate from live source permissions."""

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mcp import revisions
from app.modules.mcp.models import McpPolicy, McpService, McpSnapshot
from app.modules.mcp.service import definition_hash


async def capture(
    db: AsyncSession, service_id: UUID, tools: list[str] | None, owner_id: UUID | None = None
) -> dict[str, str] | None:
    if tools is None:
        return None  # Legacy dynamic selection is not evidence of a locked contract.
    result = {}
    for name in tools:
        rule = await db.get(McpPolicy, (service_id, "tools", name), populate_existing=True)
        if not rule or not rule.enabled or len(rule.definition_hash) != 64:
            return None
        result[name] = rule.definition_hash
    if result and owner_id is not None:
        snapshot = await db.get(McpSnapshot, (service_id, owner_id), populate_existing=True)
        if not snapshot or not snapshot.checked_at or snapshot.error:
            return None
        entries = {c["key"]: c for c in snapshot.capabilities if c["kind"] == "tools"}
        if any(
            name not in entries or definition_hash(entries[name]["definition"]) != digest
            for name, digest in result.items()
        ):
            return None
    return result


async def policy_state(
    db: AsyncSession, connector_id: UUID, ref: dict[str, Any]
) -> Literal["unverified", "version_conflict", "available"]:
    locked = ref.get("tool_contracts")
    if locked is None:
        return "unverified"
    if set(locked) != set(ref.get("tools") or []):
        return "version_conflict"
    policies = {
        r.key: r
        for r in (
            await db.scalars(
                select(McpPolicy)
                .where(McpPolicy.service_id == connector_id, McpPolicy.kind == "tools")
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    if any(
        not policies.get(name)
        or not policies[name].enabled
        or policies[name].definition_hash != digest
        for name, digest in locked.items()
    ):
        return "version_conflict"
    return "available"


async def state(
    db: AsyncSession, connector: McpService, owner_id: UUID, ref: dict[str, Any]
) -> Literal["unverified", "version_conflict", "available"]:
    locked = ref.get("tool_contracts")
    if locked is None:
        return "unverified"
    if set(locked) != set(ref.get("tools") or []):
        return "version_conflict"
    policy = await policy_state(db, connector.id, ref)
    if policy != "available":
        return policy
    if not locked:
        return "available"
    snapshot = await db.get(McpSnapshot, (connector.id, owner_id), populate_existing=True)
    if not snapshot or not snapshot.checked_at:
        return "unverified"
    entries = {c["key"]: c for c in snapshot.capabilities if c["kind"] == "tools"}
    if any(
        name not in entries or definition_hash(entries[name]["definition"]) != digest
        for name, digest in locked.items()
    ):
        return "version_conflict"
    return "available"


def matches(ref: dict[str, Any], entry: dict[str, Any]) -> bool:
    locked = ref.get("tool_contracts")
    return locked is None or locked.get(entry["key"]) == definition_hash(entry["definition"])


async def capture_all(
    db: AsyncSession, connector: McpService, owner_id: UUID, tools: list[str] | None
) -> tuple[list[str], dict[str, dict[str, dict[str, str]]]] | None:
    """Capture exactly the administrator's allowed, successful catalog at publication."""
    snapshot = await db.get(McpSnapshot, (connector.id, owner_id), populate_existing=True)
    if not snapshot or not snapshot.checked_at or snapshot.error:
        return None
    rules = {
        (r.kind, r.key): r
        for r in (
            await db.scalars(
                select(McpPolicy)
                .where(McpPolicy.service_id == connector.id)
                .execution_options(populate_existing=True)
            )
        ).all()
    }
    selected = set(tools) if tools is not None else None
    result: dict[str, dict[str, dict[str, str]]] = {kind: {} for kind in revisions.KINDS}
    for entry in snapshot.capabilities:
        kind, key = entry["kind"], entry["key"]
        rule = rules.get((kind, key))
        if (
            not rule
            or not rule.enabled
            or rule.definition_hash != definition_hash(entry["definition"])
        ):
            continue
        if kind == "tools" and selected is not None and key not in selected:
            continue
        result[kind][key] = {
            "contract": revisions.contract(entry, snapshot.protocol),
            "behavior": revisions.behavior(
                entry, await revisions.source_body(db, connector, entry)
            ),
        }
    if selected is not None and selected != set(result["tools"]):
        return None
    return sorted(result["tools"]), result


def valid_proof(ref: dict[str, Any]) -> bool:
    proof = ref.get("capability_contracts")
    return (
        isinstance(proof, dict)
        and set(proof) == set(revisions.KINDS)
        and all(isinstance(proof[k], dict) for k in revisions.KINDS)
        and set(ref.get("tools") or []) == set(proof["tools"])
    )


async def current_state_v3(
    db: AsyncSession, connector: McpService, owner_id: UUID, ref: dict[str, Any]
) -> tuple[
    Literal["available", "unverified", "version_conflict"], Literal["contract", "behavior"] | None
]:
    if not valid_proof(ref):
        return "unverified", None
    current = await capture_all(db, connector, owner_id, None)
    if current is None:
        return "unverified", None
    _, actual = current
    for kind in revisions.KINDS:
        for key, expected in ref["capability_contracts"][kind].items():
            observed = actual[kind].get(key)
            if observed is None or observed["contract"] != expected.get("contract"):
                return "version_conflict", "contract"
            if observed["behavior"] != expected.get("behavior"):
                return "version_conflict", "behavior"
    return "available", None


async def matches_v3(
    db: AsyncSession,
    connector: McpService,
    ref: dict[str, Any],
    entry: dict[str, Any],
    protocol: str,
) -> str | None:
    if not valid_proof(ref):
        return "unverified"
    expected = ref["capability_contracts"].get(entry["kind"], {}).get(entry["key"])
    if expected is None:
        return "not_selected"
    if revisions.contract(entry, protocol) != expected["contract"]:
        return "contract_changed"
    if (
        revisions.behavior(entry, await revisions.source_body(db, connector, entry))
        != expected["behavior"]
    ):
        return "behavior_changed"
    return None


async def published_state_v3(
    db: AsyncSession, connector: McpService, ref: dict[str, Any]
) -> tuple[
    Literal["available", "unverified", "version_conflict"], Literal["contract", "behavior"] | None
]:
    """Conservative console status across successful owner catalogs."""
    if not valid_proof(ref):
        return "unverified", None
    snapshots = (
        await db.scalars(
            select(McpSnapshot).where(
                McpSnapshot.service_id == connector.id,
                McpSnapshot.checked_at.is_not(None),
                McpSnapshot.error.is_(None),
            )
        )
    ).all()
    if not snapshots:
        return "unverified", None
    for snapshot in snapshots:
        status, changed = await current_state_v3(db, connector, snapshot.owner_id, ref)
        if status != "available":
            return status, changed
    return "available", None
