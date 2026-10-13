"""Explicit provider modules; database configuration never loads executable code."""

from app.modules.llm.providers.base import ChannelProvider
from app.modules.llm.providers.openai_compatible import OpenAICompatible
from app.modules.llm.providers.presets import PRESETS

PROVIDERS: dict[str, ChannelProvider] = {p.info.id: p for p in [*PRESETS, OpenAICompatible()]}
