"""Pure channel management rules shared by writes and read projections."""

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException, Request

from app.modules.auth.service import provider
from app.modules.llm.models import ModelChannel
from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.connection import (
    Operation,
    compatibility_base_url,
    legacy_connection,
    resolve_stored_connection,
    stored_connection,
)
from app.modules.llm.schemas import (
    ChannelConnectionSettings,
    ChannelInput,
    ConnectionInput,
    TestDefaults,
    TestDefaultsStatus,
)

API_OPERATIONS: dict[str, Operation] = {
    "chat_completions": "chat",
    "embeddings": "embedding",
    "rerank": "rerank",
    "images": "image_generation",
    "speech": "speech",
    "transcriptions": "transcription",
}
TEST_ENDPOINTS = {
    "chat": "chat_completions",
    "embedding": "embeddings",
    "rerank": "rerank",
    "image_generation": "images",
    "speech": "speech",
}


def receipt_digest(request: Request, body: ChannelInput) -> str:
    """HMAC the complete effective request; never store a replayable secret."""
    secret = provider(request).settings.session_encryption_key
    if secret is None:
        raise HTTPException(503, "管理回执密钥尚未配置")
    payload = body.model_dump(mode="json", exclude={"api_key", "request_id"})
    payload["api_key"] = body.api_key.get_secret_value() if body.api_key else None
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hmac.new(secret.get_secret_value().encode(), data.encode(), hashlib.sha256).hexdigest()


def effective_connection(
    body: ConnectionInput, row: ModelChannel | None, fields: set[str] | None = None
) -> tuple[str, dict[str, Any]]:
    """Old clients retaining the current base do not reset a newer address mode."""
    fields = fields if fields is not None else body.model_fields_set
    try:
        if body.connection is not None and "connection" in fields:
            connection = body.connection.resolved()
        elif (
            row is not None
            and "connection" not in fields
            and ("base_url" not in fields or body.base_url == row.base_url)
        ):
            connection = stored_connection(row.base_url, row.connection)
        else:
            if not body.base_url:
                raise ValueError("缺少服务地址")
            connection = legacy_connection(body.base_url)
        resolve_stored_connection(
            body.provider,
            body.base_url or (row.base_url if row else ""),
            vars(connection),
            operations=(
                None
                if connection.address_mode == "legacy_api_base"
                else tuple(
                    API_OPERATIONS[api] for api in body.declared_apis if api in API_OPERATIONS
                )
            ),
        )
        # The old base_url field remains a compatibility projection only.
        base = compatibility_base_url(body.provider, connection)
        if not base:
            raise ValueError("地址解析失败")
        return base, {k: v for k, v in vars(connection).items() if v is not None}
    except ValueError as exc:
        raise HTTPException(422, "地址模式、接口前缀或供应商操作组合无效") from exc


def execution_address_signature(
    provider_id: str, base_url: str, value: Mapping[str, Any] | None
) -> object:
    """Ignore address-mode bookkeeping when all effective targets are identical."""
    try:
        resolved = resolve_stored_connection(provider_id, base_url, value)
        return (
            resolved.directory_url,
            tuple(
                (target.operation, target.url, target.sdk_api_base, target.sdk_expected_url)
                for target in resolved.operation_targets
            ),
        )
    except ValueError:
        return (base_url, dict(value or {}))


def validate_registered_targets(
    provider_id: str,
    base_url: str,
    connection: Mapping[str, Any] | None,
    models: list[dict[str, Any]],
) -> None:
    """A new Gemini target must safely encode each registered upstream ID."""
    if (
        provider_id != "gemini"
        or not connection
        or connection.get("address_mode") == "legacy_api_base"
    ):
        return
    try:
        for item in models:
            resolve_stored_connection(
                provider_id,
                base_url,
                connection,
                model=item["id"],
                operations=("chat",),
            )
    except ValueError as exc:
        raise HTTPException(
            422,
            "Gemini 请填写模型短 ID（如 foo），不要包含 models/ 前缀或路径分隔符",
        ) from exc


def default_status(
    value: TestDefaults | None,
    *,
    provider_id: str,
    declared_apis: list[str],
    models: list[dict[str, Any]],
) -> TestDefaultsStatus | None:
    if value is None:
        return None
    if not any(item["id"] == value.upstream_id for item in models):
        return TestDefaultsStatus(valid=False, reason="model_missing")
    info = PROVIDERS.get(provider_id)
    if info is None or value.operation not in info.info.test_operations:
        return TestDefaultsStatus(valid=False, reason="operation_unsupported")
    if value.endpoint != TEST_ENDPOINTS[value.operation] or (
        value.operation != "speech" and value.endpoint not in declared_apis
    ):
        return TestDefaultsStatus(valid=False, reason="endpoint_unsupported")
    # Only the current SDK Chat diagnostic has a streaming execution path.
    if value.stream and value.operation != "chat":
        return TestDefaultsStatus(valid=False, reason="stream_unsupported")
    return TestDefaultsStatus(valid=True, reason="ready")


def stored_defaults(row: ModelChannel) -> TestDefaults | None:
    return TestDefaults.model_validate(row.test_defaults) if row.test_defaults else None


def stored_connection_view(row: ModelChannel) -> ChannelConnectionSettings:
    connection = stored_connection(row.base_url, row.connection)
    return ChannelConnectionSettings.model_validate(vars(connection))
