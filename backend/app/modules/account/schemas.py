from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]

    @field_validator("name")
    @classmethod
    def printable_name(cls, value: str) -> str:
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("姓名不能包含控制字符")
        return value
