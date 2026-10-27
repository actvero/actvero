"""Pure, versioned channel address resolution; never performs network I/O.

The caller still enforces the existing outbound DNS/origin policy for every
request. A resolved URL is a preview and an execution input, not authorization.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, urlsplit

from app.core.outbound import endpoint
from app.modules.llm.providers.profiles import PROFILES
from app.modules.llm.providers.profiles import Operation as Operation

AddressMode = Literal["provider_default", "service_root", "legacy_api_base"]

RESOLVER_VERSION = 1

# A snapshot, deliberately independent of future remote provider metadata.
DEFAULT_SERVICE_ROOTS = {key: p.service_root for key, p in PROFILES.items() if p.service_root}
_ALLOWED = {key: p.operations for key, p in PROFILES.items()}


@dataclass(frozen=True, kw_only=True)
class ChannelConnection:
    address_mode: AddressMode
    service_root: str | None = None
    api_prefix: str | None = None
    legacy_base_url: str | None = None
    resolver_version: int = RESOLVER_VERSION


@dataclass(frozen=True)
class OperationTarget:
    operation: Operation
    method: Literal["POST"]
    url: str
    outbound_protocol: Literal["openai_compatible", "anthropic_messages", "gemini_generate_content"]
    sdk_provider: Literal["openai", "cohere", "anthropic", "gemini"]
    sdk_api_base: str
    # Cohere rerank needs the existing exact URL mapping in RuntimeTransport.
    sdk_expected_url: str


@dataclass(frozen=True)
class ResolvedConnection:
    address_mode: AddressMode
    resolver_version: int
    directory_url: str | None
    directory_method: Literal["GET"]
    operation_targets: tuple[OperationTarget, ...]
    warnings: tuple[str, ...]


def legacy_connection(base_url: str) -> ChannelConnection:
    """Wrap a stored base without modifying the stored value or its old targets."""
    return ChannelConnection(address_mode="legacy_api_base", legacy_base_url=base_url)


def stored_connection(base_url: str, value: Mapping[str, Any] | None) -> ChannelConnection:
    """Read a saved JSON connection; an empty value is an unchanged legacy row."""
    if value is None or value == {}:
        return legacy_connection(base_url)
    allowed = {"address_mode", "service_root", "api_prefix", "legacy_base_url", "resolver_version"}
    if not isinstance(value, Mapping) or set(value) - allowed or "address_mode" not in value:
        raise ValueError("无效连接配置")
    if any(
        item is not None and not isinstance(item, str)
        for item in (
            value.get("service_root"),
            value.get("api_prefix"),
            value.get("legacy_base_url"),
        )
    ):
        raise ValueError("无效连接配置")
    version = value.get("resolver_version", RESOLVER_VERSION)
    if type(version) is not int:
        raise ValueError("无效连接版本")
    return ChannelConnection(
        address_mode=value["address_mode"],
        service_root=value.get("service_root"),
        api_prefix=value.get("api_prefix"),
        legacy_base_url=value.get("legacy_base_url"),
        resolver_version=version,
    )


def resolve_stored_connection(
    provider_id: str,
    base_url: str,
    value: Mapping[str, Any] | None,
    *,
    model: str | None = None,
    operations: tuple[Operation, ...] | None = None,
    stream: bool = False,
) -> ResolvedConnection:
    return resolve_connection(
        provider_id,
        stored_connection(base_url, value),
        model=model,
        operations=operations,
        stream=stream,
    )


def compatibility_base_url(provider_id: str, connection: ChannelConnection) -> str:
    """Old field projection only; new execution must consume connection JSON."""
    if connection.address_mode == "legacy_api_base":
        resolve_connection(provider_id, connection, operations=())
        assert connection.legacy_base_url is not None
        return connection.legacy_base_url
    target = resolve_connection(provider_id, connection, operations=("chat",)).operation_targets[0]
    return target.sdk_api_base


def _base(value: str, *, legacy: bool = False) -> str:
    # urlsplit() reports an empty query/fragment for a trailing delimiter.
    # Reject the raw delimiters before composing any directory or SDK path.
    if "?" in value or "#" in value:
        raise ValueError("地址不能包含查询参数或片段分隔符")
    endpoint(value)
    parsed = urlsplit(value)
    path_parts = parsed.path.strip("/").split("/") if parsed.path.strip("/") else []
    if (
        not legacy
        and parsed.path
        and (
            any(c in parsed.path for c in ("\\", "%"))
            or "//" in parsed.path
            or any(p in (".", "..") or not re.fullmatch(r"[A-Za-z0-9._~-]+", p) for p in path_parts)
        )
    ):
        raise ValueError("地址路径无效")
    return value.rstrip("/")


def _prefix(value: str) -> str:
    if value == "":
        return ""
    if "//" in value:
        raise ValueError("接口前缀必须是同源相对路径")
    value = value.rstrip("/")
    if (
        not value.startswith("/")
        or value.startswith("//")
        or value == "/"
        or any(ch in value for ch in ("?", "#", "@", "\\", "%"))
        or any(part in ("", ".", "..") for part in value[1:].split("/"))
        or any(not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in value[1:].split("/"))
        or len(value) > 200
    ):
        raise ValueError("接口前缀必须是同源相对路径")
    return value


def _model_segment(model: str | None) -> str:
    if model is None:
        return "{mapped_model}"
    # The SDK inserts the upstream model as one path segment. Reject models
    # whose encoding would yield an ambiguous or different SDK destination.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}", model):
        raise ValueError("Gemini 上游模型名称不能安全组成目标路径")
    return quote(model, safe="-._~")


def resolve_connection(
    provider_id: str,
    connection: ChannelConnection,
    *,
    model: str | None = None,
    operations: tuple[Operation, ...] | None = None,
    stream: bool = False,
) -> ResolvedConnection:
    """Resolve directory and explicitly allowed operation targets for one channel.

    `model` is the binding's upstream name, never the public model slug. A
    Gemini preview without it uses a placeholder and must not be executed.
    """
    if provider_id not in _ALLOWED:
        raise ValueError("未知供应商")
    if connection.resolver_version != RESOLVER_VERSION:
        raise ValueError("未知地址解析版本")
    if connection.address_mode == "provider_default":
        if connection.service_root is not None or connection.legacy_base_url is not None:
            raise ValueError("默认地址模式不能携带自定义地址")
        if provider_id not in DEFAULT_SERVICE_ROOTS:
            raise ValueError("该供应商没有默认服务地址")
        root = _base(DEFAULT_SERVICE_ROOTS[provider_id])
    elif connection.address_mode == "service_root":
        if not connection.service_root or connection.legacy_base_url is not None:
            raise ValueError("服务根地址模式需要唯一根地址")
        root = _base(connection.service_root)
        if any(part.lower() in ("v1", "v1beta") for part in urlsplit(root).path.split("/")):
            raise ValueError("API 基础 URL 请勿包含 /v1 或 /v1beta；特殊版本请在接口前缀中配置")
    elif connection.address_mode == "legacy_api_base":
        if not connection.legacy_base_url or connection.service_root is not None:
            raise ValueError("旧地址模式需要原始 base_url")
        root = _base(connection.legacy_base_url, legacy=True)
    else:
        raise ValueError("未知地址模式")
    warnings: tuple[str, ...]
    if connection.address_mode == "legacy_api_base":
        if connection.api_prefix is not None:
            raise ValueError("旧地址模式不能覆盖接口前缀")
        base = root
        directory: str | None = base + (
            "/v1/models"
            if provider_id == "anthropic"
            else "/v1beta/models"
            if provider_id == "gemini"
            else "/models"
        )
        warnings = ("legacy_base_preserved",)
    else:
        prefix = (
            _prefix(connection.api_prefix)
            if connection.api_prefix is not None
            else PROFILES[provider_id].api_prefix
        )
        base = root + prefix
        directory = base + "/models"
        warnings = ()
    if provider_id == "aliyun-bailian" and base.endswith("/compatible-mode/v1"):
        directory = base.removesuffix("/compatible-mode/v1") + "/api/v1/models"
    if not PROFILES[provider_id].model_discovery:
        directory = None
        warnings += ("manual_model_registration",)
    requested = operations if operations is not None else _ALLOWED[provider_id]
    if len(requested) != len(set(requested)) or any(
        op not in _ALLOWED[provider_id] for op in requested
    ):
        raise ValueError("该供应商/操作组合尚未接入")
    if stream and any(op != "chat" for op in requested):
        raise ValueError("该操作没有流式目标")
    targets: list[OperationTarget] = []
    for operation in requested:
        protocol: Literal["openai_compatible", "anthropic_messages", "gemini_generate_content"]
        sdk_provider: Literal["openai", "cohere", "anthropic", "gemini"]
        if provider_id == "anthropic":
            # LiteLLM's native chat adapter appends /v1/messages to its base.
            sdk_base = root
            url = (
                root + "/v1/messages"
                if connection.address_mode == "legacy_api_base"
                else base + "/messages"
            )
            protocol = "anthropic_messages"
            sdk_provider = "anthropic"
            expected = root + "/v1/messages"
        elif provider_id == "gemini":
            # Native SDK appends /models/{model}:... to its api_base.
            sdk_base = base
            suffix = ":streamGenerateContent?alt=sse" if stream else ":generateContent"
            url = base + "/models/" + _model_segment(model) + suffix
            protocol = "gemini_generate_content"
            sdk_provider = "gemini"
            expected = url
        else:
            paths = {
                "chat": "/chat/completions",
                "embedding": "/embeddings",
                "rerank": "/rerank",
                "image_generation": "/images/generations",
                "speech": "/audio/speech",
                "transcription": "/audio/transcriptions",
            }
            url = base + paths[operation]
            protocol = "openai_compatible"
            sdk_provider = "cohere" if operation == "rerank" else "openai"
            sdk_base = base + "/v1/rerank" if operation == "rerank" else base
            expected = sdk_base if operation == "rerank" else url
        targets.append(
            OperationTarget(operation, "POST", url, protocol, sdk_provider, sdk_base, expected)
        )
    return ResolvedConnection(
        connection.address_mode,
        connection.resolver_version,
        directory,
        "GET",
        tuple(targets),
        warnings,
    )
