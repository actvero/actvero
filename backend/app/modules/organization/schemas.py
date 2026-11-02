from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OrganizationSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    created_at: datetime


class OrganizationSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=60)
    expected_name: str = Field(min_length=2, max_length=60)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: object) -> object:
        if isinstance(value, str):
            if any(ord(char) < 32 or ord(char) == 127 for char in value):
                raise ValueError("组织名称不能包含控制字符")
            return value.strip()
        return value
