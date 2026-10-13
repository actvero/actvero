"""Tenant-local inventory matching; candidate discovery never enables a route."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.llm.catalog_schemas import OperationKind
from app.modules.llm.models import ModelChannel
from app.modules.llm.providers import PROVIDERS

MatchMode = Literal["exact", "prefix", "suffix", "contains"]
APIS: dict[OperationKind, str] = {
    "chat": "chat_completions",
    "embedding": "embeddings",
    "rerank": "rerank",
    "image_generation": "images",
    "speech": "speech",
    "transcription": "transcriptions",
}


class ModelCandidate(BaseModel):
    channel_id: UUID
    channel_name: str
    channel_version: int
    upstream_id: str
    manual_enabled: bool
    operations: list[OperationKind]


class ModelCandidatePage(BaseModel):
    items: list[ModelCandidate]
    total: int
    page: int
    page_size: int = 50


def matches(name: str, query: str, mode: MatchMode) -> bool:
    # Literal, case-sensitive matching, including %, _, * and regex metacharacters.
    if mode == "exact":
        return name == query
    if mode == "prefix":
        return name.startswith(query)
    if mode == "suffix":
        return name.endswith(query)
    return query in name


def candidates(
    channels: list[ModelChannel], query: str, mode: MatchMode, kind: OperationKind, page: int
) -> ModelCandidatePage:
    result: list[ModelCandidate] = []
    for channel in channels:
        module = PROVIDERS.get(channel.provider)
        if channel.archived or module is None:
            continue
        operations = [
            operation
            for operation in APIS
            if operation in module.info.member_operations
            and APIS[operation] in channel.declared_apis
        ]
        if kind not in operations:
            continue
        seen: set[str] = set()
        for item in channel.models:
            model_id = item.get("id")
            if (
                not isinstance(model_id, str)
                or model_id in seen
                or (query and not matches(model_id, query, mode))
            ):
                continue
            seen.add(model_id)
            result.append(
                ModelCandidate(
                    channel_id=channel.id,
                    channel_name=channel.name,
                    channel_version=channel.version,
                    upstream_id=model_id,
                    manual_enabled=channel.manual_enabled is not False,
                    operations=operations,
                )
            )
    result.sort(key=lambda item: (item.channel_name, str(item.channel_id), item.upstream_id))
    start = (page - 1) * 50
    return ModelCandidatePage(items=result[start : start + 50], total=len(result), page=page)
