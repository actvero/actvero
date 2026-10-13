"""Versioned built-in provider modules. No database-supplied executable code."""

from typing import Any

from app.modules.llm.providers.openai_compatible import OpenAICompatible
from app.modules.llm.providers.profiles import PROFILES
from app.modules.llm.schemas import ProviderId, ProviderView, ReferenceCatalog


class Preset(OpenAICompatible):
    def __init__(self, info: ProviderView) -> None:
        profile = PROFILES[info.id]
        info.official_service_root = profile.service_root
        info.default_api_prefix = profile.api_prefix
        info.model_discovery = profile.model_discovery
        # Retain the historical SDK-base projection for old clients, while
        # displaying the actual service root/prefix independently in new UI.
        info.default_base_url = profile.service_root + (
            "" if info.id in {"anthropic", "gemini"} else profile.api_prefix
        )
        self.info = info


class Anthropic(Preset):
    sdk_provider = "anthropic"

    def headers(self, key: str | None) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "x-api-key": key or "",
            "anthropic-version": "2023-06-01",
        }


class Gemini(Preset):
    sdk_provider = "gemini"

    def headers(self, key: str | None) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "x-goog-api-key": key or "",
        }

    def entries(self, payload: dict[str, Any]) -> tuple[list[Any], bool]:
        return payload["models"], bool(payload.get("nextPageToken"))

    def model_id(self, item: dict[str, Any]) -> str:
        value = item["name"]
        if not isinstance(value, str) or not value.startswith("models/"):
            raise ValueError("Invalid model resource")
        return value.removeprefix("models/")


ROOT_HELP = "填写服务根地址，不附加 /v1、/v1beta 或具体调用路径。"


def ordinary_api(
    provider_id: ProviderId, name: str, icon: str, aliases: list[str], help_text: str
) -> Preset:
    profile = PROFILES[provider_id]
    return Preset(
        ProviderView(
            id=provider_id,
            name=name,
            icon_key=icon,
            category="aggregator" if provider_id == "aihubmix" else "vendor",
            aliases=aliases,
            base_url_help=ROOT_HELP,
            setup_help=help_text,
            model_discovery=profile.model_discovery,
            balance_query=False,
            member_inference=True,
            member_operations=["chat"],
            test_operations=["chat"],
        )
    )


PRESETS = [
    Preset(
        ProviderView(
            id="openai",
            version=4,
            name="OpenAI",
            icon_key="openai",
            category="vendor",
            aliases=["GPT", "ChatGPT"],
            model_discovery=True,
            balance_query=False,
            member_inference=True,
            member_operations=[
                "chat",
                "embedding",
                "rerank",
                "image_generation",
                "speech",
                "transcription",
            ],
            test_operations=["chat", "embedding", "rerank", "image_generation", "speech"],
        )
    ),
    Anthropic(
        ProviderView(
            id="anthropic",
            name="Anthropic",
            default_apis=["chat_completions"],
            member_inference=True,
            member_operations=["chat"],
            icon_key="anthropic",
            category="vendor",
            aliases=["Claude"],
            base_url_help=ROOT_HELP,
            model_discovery=True,
            balance_query=False,
        )
    ),
    Gemini(
        ProviderView(
            id="gemini",
            name="Gemini",
            default_apis=["chat_completions"],
            member_inference=True,
            member_operations=["chat"],
            icon_key="gemini",
            category="vendor",
            aliases=["Google", "谷歌", "AI Studio"],
            base_url_help=ROOT_HELP,
            model_discovery=True,
            balance_query=False,
        )
    ),
    Preset(
        ProviderView(
            id="deepseek",
            name="DeepSeek",
            icon_key="deepseek",
            category="vendor",
            aliases=["深度求索"],
            model_discovery=True,
            balance_query=False,
            member_inference=True,
            member_operations=["chat", "embedding", "rerank"],
            test_operations=["chat", "embedding", "rerank"],
        )
    ),
    Preset(
        ProviderView(
            id="siliconflow",
            name="硅基流动",
            icon_key="siliconcloud",
            category="aggregator",
            aliases=["SiliconFlow", "SiliconCloud"],
            model_discovery=True,
            balance_query=False,
            member_inference=True,
            member_operations=["chat", "embedding", "rerank"],
            test_operations=["chat", "embedding", "rerank"],
        )
    ),
    ordinary_api(
        "aihubmix",
        "AIHubMix",
        "aihubmix",
        ["AI Hub Mix"],
        "使用 AIHubMix 普通 API Key，当前预设接入对话。"
        "模型目录只登记 ID，不自动设置价格或开放调用。",
    ),
    ordinary_api(
        "volcengine",
        "火山方舟",
        "volcengine",
        ["Ark", "Doubao", "豆包", "火山引擎"],
        "使用火山方舟普通 API Key；填写已开通的模型 ID 或 ep- 接入点 ID。"
        "Agent Plan / Coding Plan 请勿使用此预设。",
    ),
    ordinary_api(
        "zhipu",
        "智谱 GLM",
        "zhipu",
        ["Zhipu", "GLM", "BigModel"],
        "使用智谱中国站普通 API Key，当前预设接入对话。"
        "GLM Coding Plan 和 Z.ai 国际站请勿使用此预设。",
    ),
    ordinary_api(
        "moonshot",
        "Kimi",
        "moonshot",
        ["Moonshot", "月之暗面"],
        "使用 Kimi 开放平台普通 API Key，当前预设接入对话。Kimi Code 套餐请勿使用此预设。",
    ),
    ordinary_api(
        "qwen",
        "千问按量 API",
        "bailian",
        ["Qwen", "通义千问", "千问"],
        "使用千问 AI 平台按量 API Key。Token Plan 套餐请勿使用此预设；"
        "原阿里云百炼 DashScope 地址请保留原配置。",
    ),
    Preset(
        ProviderView(
            id="qwen-token-plan",
            name="千问 Token Plan（团队版）",
            category="vendor",
            icon_key="bailian",
            aliases=["阿里云", "Alibaba", "Qwen", "通义千问", "Token Plan", "团队套餐"],
            base_url_help=ROOT_HELP,
            setup_help=(
                "使用团队成员席位对应的 sk-sp- 套餐专属 API Key；普通按量 Key 不适用。"
                "当前接入对话、流式和工具调用，模型需在套餐内。"
                "Key 归属对应席位，调用范围请按该席位配置。"
            ),
            model_discovery=False,
            balance_query=False,
            member_inference=True,
            member_operations=["chat"],
            test_operations=["chat"],
            reference_catalog=ReferenceCatalog(
                models=[
                    "qwen3.8-max",
                    "qwen3.8-flash",
                    "qwen3.7-max",
                    "qwen3.7-plus",
                    "qwen3.6-plus",
                    "qwen3.6-flash",
                    "deepseek-v4-pro",
                    "deepseek-v4-pro-0813",
                    "deepseek-v4-flash",
                    "deepseek-v4-flash-0731",
                    "deepseek-v3.2",
                    "kimi-k2.7-code",
                    "kimi-k2.6",
                    "kimi-k2.5",
                    "glm-5.2",
                    "glm-5.1",
                    "glm-5",
                    "MiniMax-M2.5",
                ],
                source_url="https://platform.qianwenai.com/docs/token-plan/team/token-plan-team-overview",
                checked_at="2026-10-04",
            ),
        )
    ),
]

# Preserve previously shipped product IDs and saved credentials/targets independently.
# Their catalogs require separate control-plane credentials; register models manually.
PRESETS.extend(
    [
        ordinary_api(
            "aliyun-bailian",
            "阿里百炼 · 普通 API",
            "bailian",
            ["DashScope"],
            "使用百炼普通 API Key；普通 API 与千问 Token Plan 分开；模型请手动登记。",
        ),
        ordinary_api(
            "volcengine-agent-plan",
            "火山方舟 Agent Plan",
            "volcengine",
            ["Agent Plan", "Ark"],
            "使用 Agent Plan 专属 Key 与接入点，不使用普通方舟凭据。模型请手动登记。",
        ),
        ordinary_api(
            "volcengine-coding-plan",
            "火山方舟 Coding Plan",
            "volcengine",
            ["Coding Plan", "Ark"],
            "使用 Coding Plan 专属 Key 与模型 ID，不使用普通方舟凭据。模型请手动登记。",
        ),
    ]
)
