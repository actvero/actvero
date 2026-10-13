from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings
from app.modules.llm.schemas import ProviderView, UpstreamModel


@dataclass
class ModelListing:
    models: list[UpstreamModel]
    partial: bool = False


class ChannelProvider(Protocol):
    info: ProviderView
    sdk_provider: str

    async def list_models(
        self,
        base_url: str,
        key: str | None,
        timeout: int,
        settings: Settings,
        *,
        connection: Mapping[str, Any] | None = None,
    ) -> ModelListing: ...
