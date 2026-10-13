"""Freeze historical name-derived routes into explicit tenant-scoped bindings.

Revision ID: 102w_freeze_legacy_routes
Revises: 101v_repository_consolidation
"""

import copy
import json
from uuid import UUID, uuid5

import sqlalchemy as sa
from alembic import op

revision = "102w_freeze_legacy_routes"
down_revision = "101v_repository_consolidation"
branch_labels = None
depends_on = None

# Frozen migration contract, deliberately independent of future provider modules.
_APIS = {
    "chat": "chat_completions",
    "embedding": "embeddings",
    "rerank": "rerank",
    "image_generation": "images",
    "speech": "speech",
    "transcription": "transcriptions",
}
_NATIVE_CHAT = {
    "anthropic",
    "gemini",
    "aliyun-bailian",
    "volcengine",
    "zhipu",
    "moonshot",
    "bailian-token-plan",
    "volcengine-coding-plan",
    "volcengine-agent-plan",
}
_COMPATIBLE = {"openai", "openai-compatible", "aihubmix"}
_RETRIEVAL = {"deepseek", "siliconflow"}


def freeze(model_id: str, configuration: dict, channels: list[dict]) -> dict:
    """Preserve existing explicit rows and materialize only the old effective set."""
    data = copy.deepcopy(configuration)
    scopes = data.get("operations")
    if not isinstance(scopes, list):
        scopes = [data]
    for scope in scopes:
        policy = scope.get("routing") or {}
        if "source" not in policy:
            continue
        source = policy.pop("source")
        scope["routing"] = policy
        if source != "channels":
            continue
        kind = scope.get("kind", "chat")
        existing = {(b["channel_id"], b["upstream_id"]): b for b in scope.get("bindings", [])}
        found = []
        for channel in sorted(channels, key=lambda row: str(row["id"])):
            provider = channel["provider"]
            if channel["archived"] or provider not in _NATIVE_CHAT | _COMPATIBLE | _RETRIEVAL:
                continue
            if provider in _NATIVE_CHAT and kind != "chat":
                continue
            if provider in _RETRIEVAL and kind not in {"chat", "embedding", "rerank"}:
                continue
            if _APIS.get(kind) not in channel["declared_apis"]:
                continue
            route = channel["routing"] or {}
            upstream = (route.get("model_mapping") or {}).get(data["slug"], data["slug"])
            if not any(item.get("id") == upstream for item in channel["models"]):
                continue
            cid = str(channel["id"])
            binding = copy.deepcopy(existing.get((cid, upstream), {}))
            binding.update(
                channel_id=cid,
                upstream_id=upstream,
                priority=route.get("priority", 0),
                weight=route.get("weight", 100),
                enabled=route.get("enabled", True) and binding.get("enabled", True),
            )
            if not binding.get("binding_id"):
                binding["binding_id"] = str(
                    uuid5(UUID(model_id), json.dumps([kind, cid, upstream], separators=(",", ":")))
                )
            found.append(binding)
        # The historical model stored overrides; effective bindings replace that derived set.
        scope["bindings"] = found
        if kind in {"speech", "transcription", "image_generation"}:
            enabled = [b for b in found if b["enabled"]]
            if len(enabled) > 1:
                raise RuntimeError(
                    f"Model {model_id}: select one historical media route before migration"
                )
            policy["mode"] = "fixed"
            policy["fallback"] = False
            if enabled:
                target = enabled[0]
                if scope is data:
                    access = scope.setdefault("access", {})
                    access.update(
                        channel_id=target["channel_id"], upstream_id=target["upstream_id"]
                    )
                else:
                    scope.update(channel_id=target["channel_id"], upstream_id=target["upstream_id"])
    # Derived display fields can contain the legacy source even with operations present.
    if isinstance(data.get("routing"), dict):
        data["routing"].pop("source", None)
    return data


def upgrade() -> None:
    connection = op.get_bind()
    channels = (
        connection.execute(
            sa.text(
                "SELECT id, tenant_id, provider, archived, declared_apis, models, routing "
                "FROM model_channels"
            )
        )
        .mappings()
        .all()
    )
    models = (
        connection.execute(sa.text("SELECT id, tenant_id, configuration FROM llm_models"))
        .mappings()
        .all()
    )
    for model in models:
        configuration = freeze(
            str(model["id"]),
            model["configuration"],
            [dict(c) for c in channels if c["tenant_id"] == model["tenant_id"]],
        )
        if configuration != model["configuration"]:
            connection.execute(
                sa.text("UPDATE llm_models SET configuration=CAST(:value AS jsonb) WHERE id=:id"),
                {"id": model["id"], "value": json.dumps(configuration)},
            )


def downgrade() -> None:
    raise RuntimeError(
        "Cannot restore dynamic matching automatically; restore the pre-upgrade backup"
    )
