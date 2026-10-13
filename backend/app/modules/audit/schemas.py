from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    actor_name: str
    action: str
    target_id: UUID
    target_name: str
    result: str
    details: dict[str, str]
    created_at: datetime


class EventPage(BaseModel):
    items: list[EventView]
    total: int
    page: int
    page_size: int = 20
