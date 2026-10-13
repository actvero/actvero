from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.platform.schemas import PlatformSettingsUpdate

BrandSlot = Literal["mark_light", "mark_dark", "wordmark_light", "wordmark_dark", "favicon"]


class BrandImageUpload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=2_800_000)


class BrandingUpdate(PlatformSettingsUpdate):
    model_config = ConfigDict(extra="forbid")
    revision: UUID
    assets: dict[BrandSlot, UUID | BrandImageUpload | None] = Field(max_length=5)


class PublicBranding(BaseModel):
    name: str
    revision: UUID
    assets: dict[BrandSlot, str]
    asset_ids: dict[BrandSlot, UUID]
    favicon_url: str
    apple_icon_url: str


class BrandingSettings(PublicBranding):
    identity_status: Literal["applied", "pending"]
