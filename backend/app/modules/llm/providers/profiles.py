"""Reviewed local address profiles, independent of SDK defaults and remote metadata.

These are resolver v1 snapshots. Changing a shipped target requires a versioned
migration, not an in-place refresh from a supplier's catalog. Subscription
products have separate IDs so saved ordinary API channels never change target.
"""

from dataclasses import dataclass
from typing import Literal

Operation = Literal["chat", "embedding", "rerank", "image_generation", "speech", "transcription"]


@dataclass(frozen=True)
class ProviderProfile:
    service_root: str
    api_prefix: str
    operations: tuple[Operation, ...]
    model_discovery: bool = True
    model_namespace: str | None = None
    available_for_new_channels: bool = True


_COMPATIBLE: tuple[Operation, ...] = (
    "chat",
    "embedding",
    "rerank",
    "image_generation",
    "speech",
    "transcription",
)

PROFILES = {
    "openai": ProviderProfile(
        "https://api.openai.com", "/v1", _COMPATIBLE, model_namespace="openai"
    ),
    "openai-compatible": ProviderProfile("", "/v1", _COMPATIBLE),
    "anthropic": ProviderProfile(
        "https://api.anthropic.com", "/v1", ("chat",), model_namespace="anthropic"
    ),
    "gemini": ProviderProfile(
        "https://generativelanguage.googleapis.com", "/v1beta", ("chat",), model_namespace="gemini"
    ),
    # Preserve the operation contract of already-saved channels. Any tightening
    # of historical DeepSeek declarations needs a separate binding audit.
    "deepseek": ProviderProfile(
        "https://api.deepseek.com", "", ("chat", "embedding", "rerank"), model_namespace="deepseek"
    ),
    "siliconflow": ProviderProfile(
        "https://api.siliconflow.cn",
        "/v1",
        ("chat", "embedding", "rerank"),
        model_namespace="siliconflow",
    ),
    "aihubmix": ProviderProfile("https://aihubmix.com", "/v1", ("chat",)),
    "volcengine": ProviderProfile(
        "https://ark.cn-beijing.volces.com", "/api/v3", ("chat",), True, "volcengine"
    ),
    "zhipu": ProviderProfile(
        "https://open.bigmodel.cn",
        "/api/paas/v4",
        ("chat",),
        True,
        "zai",
        available_for_new_channels=False,
    ),
    "moonshot": ProviderProfile(
        "https://api.moonshot.cn", "/v1", ("chat",), model_namespace="moonshot"
    ),
    "qwen": ProviderProfile(
        "https://maas.qianwenaiapi.com",
        "/compatible-mode/v1",
        ("chat",),
        True,
        "qwen_ai_platform",
        available_for_new_channels=False,
    ),
    # Historical products are separate snapshots, never rewritten into Qwen Team Plan.
    "aliyun-bailian": ProviderProfile(
        "https://dashscope.aliyuncs.com", "/compatible-mode/v1", ("chat",), True
    ),
    "volcengine-agent-plan": ProviderProfile(
        "https://ark.cn-beijing.volces.com",
        "/api/plan/v3",
        ("chat",),
        True,
        available_for_new_channels=False,
    ),
    "volcengine-coding-plan": ProviderProfile(
        "https://ark.cn-beijing.volces.com",
        "/api/coding/v3",
        ("chat",),
        True,
        available_for_new_channels=False,
    ),
    "qwen-token-plan": ProviderProfile(
        "https://token-plan.maas.qianwenaiapi.com",
        "/compatible-mode/v1",
        ("chat",),
        True,
        available_for_new_channels=False,
    ),
}
