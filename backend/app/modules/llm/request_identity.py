"""Versioned, scoped HMAC identity for one validated member inference request."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from typing import Any
from uuid import UUID

from app.core.config import Settings
from app.modules.llm.audio_schemas import SpeechInput, TranscriptionInput
from app.modules.llm.catalog_schemas import OperationKind
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.image_schemas import ImageInput
from app.modules.llm.inference_schemas import EmbeddingInput, RerankInput

InferenceRequest = (
    ChatInput | EmbeddingInput | RerankInput | ImageInput | SpeechInput | TranscriptionInput
)

_VERSION = "v1"
_DOMAIN = b"actvero.llm.member-request.v1\x00"
_BODY_TYPES: dict[OperationKind, type[InferenceRequest]] = {
    "chat": ChatInput,
    "embedding": EmbeddingInput,
    "rerank": RerankInput,
    "image_generation": ImageInput,
    "speech": SpeechInput,
    "transcription": TranscriptionInput,
}


def _reject_nonfinite(value: Any) -> None:
    # Pydantic's JSON serializer turns NaN in unconstrained nested Any into
    # null; that would collide with an actual null in a tool/schema payload.
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Member request contains a non-finite number")
    if isinstance(value, dict):
        for item in value.values():
            _reject_nonfinite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_nonfinite(item)


def request_fingerprint(
    settings: Settings,
    tenant_id: UUID,
    member_id: UUID,
    model_id: UUID,
    operation: OperationKind,
    body: InferenceRequest,
) -> str:
    """Hash the effective request without storing its replayable input.

    The caller must pass a validated operation-specific model. Credentials,
    sessions, devices and access keys intentionally are not part of the scope:
    one member's different entry points share the same idempotency identity.
    """
    expected = _BODY_TYPES.get(operation)
    if expected is None or type(body) is not expected:
        raise ValueError("Member request operation and body do not match")
    if not all(isinstance(value, UUID) for value in (tenant_id, member_id, model_id)):
        raise ValueError("Member request scope requires UUID identities")
    secret = settings.session_encryption_key
    if secret is None:
        raise ValueError("Member request fingerprint key unavailable")
    _reject_nonfinite(body.model_dump(mode="python"))
    payload = {
        "tenant_id": str(tenant_id),
        "member_id": str(member_id),
        "model_id": str(model_id),
        "operation": operation,
        "body": body.model_dump(
            mode="json", exclude_unset=False, exclude_defaults=False, exclude_none=False
        ),
    }
    if isinstance(body, TranscriptionInput):
        payload["audio_sha256"] = hashlib.sha256(body.audio).hexdigest()
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    digest = hmac.new(secret.get_secret_value().encode("utf-8"), _DOMAIN + encoded, hashlib.sha256)
    return f"{_VERSION}:{digest.hexdigest()}"


def fingerprints_equal(left: str, right: str) -> bool:
    """Compare persisted fingerprints without content-dependent timing."""
    return hmac.compare_digest(left, right)
