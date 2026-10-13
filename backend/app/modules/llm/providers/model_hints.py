"""Advisory model type from the pinned SDK's local registry, never inference."""

from app.modules.llm.providers import PROVIDERS
from app.modules.llm.providers.profiles import PROFILES
from app.modules.llm.providers.sdk import litellm
from app.modules.llm.schemas import ModelHint

API_BY_KIND = {
    "chat": "chat_completions",
    "embedding": "embeddings",
    "rerank": "rerank",
    "image_generation": "images",
    "speech": "speech",
    "transcription": "transcriptions",
}


def model_hint(provider_id: str, upstream_id: str, declared_apis: list[str]) -> ModelHint:
    provider = PROVIDERS[provider_id]
    available = [
        kind for kind in provider.info.member_operations if API_BY_KIND[kind] in declared_apis
    ]
    result = ModelHint(available_kinds=available)
    # A compatible protocol is not an assertion about the model's manufacturer.
    namespace = PROFILES[provider_id].model_namespace
    if namespace is None:
        return result
    for key in (f"{namespace}/{upstream_id}", upstream_id):
        info = litellm.model_cost.get(key)
        if not info or info.get("litellm_provider") != namespace:
            continue
        mode = info.get("mode")
        if not isinstance(mode, str) or not mode:
            continue
        result.source = "litellm"
        result.reference_key = key
        result.mode = mode
        if mode == "chat":
            for field, keys in (
                ("context_window", ("max_input_tokens", "max_tokens")),
                ("max_output", ("max_output_tokens",)),
            ):
                value = next(
                    (info[k] for k in keys if isinstance(info.get(k), int) and info[k] > 0), None
                )
                setattr(result, field, value)
            try:
                result.supported_parameters = litellm.get_supported_openai_params(
                    model=upstream_id, custom_llm_provider=provider.sdk_provider
                )
            except Exception:
                pass  # Unknown is distinct from no supported parameters.
        result.kind = next(
            (
                kind
                for kind in available
                if kind
                == {"audio_speech": "speech", "audio_transcription": "transcription"}.get(
                    mode, mode
                )
            ),
            None,
        )
        return result
    return result
