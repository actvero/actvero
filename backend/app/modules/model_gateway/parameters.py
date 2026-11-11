"""Versioned model facts; native metadata and price remain in New API."""

from typing import Any, Literal
from uuid import UUID

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from app.modules.auth.service import DB, now
from app.modules.llm.audio_schemas import SpeechOptions, TranscriptionOptions
from app.modules.llm.catalog_schemas import (
    CatalogInput,
    ModelCapabilities,
    OperationKind,
    ReasoningOption,
    RetrievalOptions,
)
from app.modules.llm.image_schemas import ImageOptions
from app.modules.llm.model_identifier import ModelIdentifier
from app.modules.llm.schemas import Input
from app.modules.members.service import Access
from app.modules.model_gateway.models import GatewayModelParameters
from app.modules.tenants.models import Tenant

FACT_FIELDS = {
    "kind",
    "context_window",
    "max_output",
    "capabilities",
    "reasoning_options",
    "retrieval",
    "image",
    "speech",
    "transcription",
    "capability_mode",
}


class ProviderMetadataInput(Input):
    model_name: ModelIdentifier
    channel_id: int = Field(gt=0)
    reference_model: str = Field(default="", max_length=128)
    workspace_id: str = Field(default="", pattern=r"^[A-Za-z0-9-]{0,64}$")


def provider_profile(raw: dict[str, Any]) -> dict[str, Any]:
    info = raw.get("model_info")
    info = info if isinstance(info, dict) else {}
    features = raw.get("features")
    features = features if isinstance(features, list) else []
    metadata = raw.get("inference_metadata")
    modalities = metadata.get("request_modality") if isinstance(metadata, dict) else []
    modalities = (
        [str(value).lower() for value in modalities] if isinstance(modalities, list) else []
    )
    capabilities = raw.get("capabilities")
    capabilities = capabilities if isinstance(capabilities, list) else []

    def limit(key: str) -> int | None:
        value = info.get(key)
        return value if type(value) is int and 0 < value <= 100000000 else None

    context, output = limit("context_window"), limit("max_output_tokens")
    return {
        "capability_mode": "manual",
        "context_window": context,
        "max_output": output if not context or not output else min(output, context - 1),
        "capabilities": {
            "tools": "supported" if "function-calling" in features else "unknown",
            "structured_output": "supported" if "structured-outputs" in features else "unknown",
            "vision": "supported"
            if "image" in modalities
            else "unsupported"
            if modalities
            else "unknown",
            "reasoning": "supported"
            if limit("max_reasoning_tokens") or "Reasoning" in capabilities
            else "unknown",
        },
        "source": {
            "provider": "aliyun-bailian",
            "model": str(raw.get("model", "")),
            "verified_at": now().isoformat(),
            "url": "https://help.aliyun.com/zh/model-studio/list-models",
        },
    }


class ModelParametersInput(Input):
    version: int = Field(default=0, ge=0)
    kind: OperationKind = "chat"
    context_window: int | None = Field(default=None, ge=1, le=100000000)
    max_output: int | None = Field(default=None, ge=1, le=100000000)
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    reasoning_options: list[ReasoningOption] = Field(default_factory=list, max_length=3)
    retrieval: RetrievalOptions = Field(default_factory=RetrievalOptions)
    image: ImageOptions = Field(default_factory=ImageOptions)
    speech: SpeechOptions = Field(default_factory=SpeechOptions)
    transcription: TranscriptionOptions = Field(default_factory=TranscriptionOptions)
    capability_mode: Literal["auto", "manual"] = "auto"
    reference_model: str = Field(default="", max_length=128)
    source: dict[str, str] = Field(default_factory=dict, max_length=12)


async def get(db: DB, tenant: UUID, name: str) -> GatewayModelParameters | None:
    return await db.get(GatewayModelParameters, (tenant, name))


async def view(db: DB, tenant: UUID, name: str) -> dict[str, Any]:
    from app.modules.model_gateway import publication

    row = await get(db, tenant, name)
    if row:
        return {
            **{
                k: v for k, v in row.configuration.items() if k in ModelParametersInput.model_fields
            },
            "version": row.version,
            "updated_at": row.updated_at.isoformat(),
        }
    legacy = publication.view(await publication.find(db, tenant, name))
    return {k: v for k, v in legacy.items() if k in FACT_FIELDS} | {
        "version": 0,
        "source": legacy.get("capability_source", {}),
    }


async def validate(db: DB, tenant: UUID, name: str, body: ModelParametersInput) -> None:
    await db.scalar(select(Tenant.id).where(Tenant.id == tenant).with_for_update())
    row = await get(db, tenant, name)
    if body.version != (row.version if row else 0):
        raise HTTPException(409, "模型资料参数已变化，请刷新后重试")
    # Validate facts without requiring routes, prices or member publication.
    from app.modules.model_gateway.publication import PublicationInput, configuration, find

    try:
        configuration(
            tenant,
            "https://gateway.example.com",
            PublicationInput(
                model_name=name, name=name[:100], **body.model_dump(include=FACT_FIELDS)
            ),
            {},
        )
    except ValueError as exc:
        raise HTTPException(422, "模型参数不匹配，请核对上下文、输出与推理选项") from exc
    published = await find(db, tenant, name)
    if published and published.configuration.get("gateway"):
        project(published.configuration, body)


def project(configuration: dict[str, Any], body: ModelParametersInput) -> dict[str, Any]:
    previous = CatalogInput.model_validate(configuration)
    if previous.kind == "embedding" and previous.retrieval != body.retrieval:
        raise HTTPException(409, "向量参数变更请使用新的模型名称")
    data = {
        **configuration,
        **body.model_dump(mode="json", include=FACT_FIELDS - {"capability_mode"}),
    }
    data["gateway"] = {
        **data["gateway"],
        "capability_mode": body.capability_mode,
        "capability_source": {
            **body.source,
            "reference_model": body.reference_model,
            "independent_parameters": "true",
        },
    }
    try:
        CatalogInput.model_validate(data)
    except ValueError as exc:
        raise HTTPException(409, "参数与已保存的使用设置不匹配，请先调整默认值或关闭开放") from exc
    return data


async def save(
    request: Request, db: DB, actor: Access, name: str, body: ModelParametersInput
) -> GatewayModelParameters:
    from app.modules.model_gateway import publication

    await validate(db, actor.tenant.id, name, body)
    row = await get(db, actor.tenant.id, name)
    if row is None:
        row = GatewayModelParameters(tenant_id=actor.tenant.id, model_name=name, version=1)
        db.add(row)
    else:
        row.version += 1
    row.configuration = body.model_dump(mode="json", exclude={"version"})
    row.updated_at = now()
    published = await publication.find(db, actor.tenant.id, name)
    if published and published.configuration.get("gateway"):
        published.configuration = project(published.configuration, body)
        published.version += 1
        published.updated_at = now()
    await db.flush()
    return row
