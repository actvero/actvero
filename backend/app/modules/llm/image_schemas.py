"""Bounded image configuration, member generation and transient media delivery."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ImageSize = Literal[
    "auto", "256x256", "512x512", "1024x1024", "1536x1024", "1024x1536", "1792x1024", "1024x1792"
]
ImageQuality = Literal["auto", "low", "medium", "high", "standard", "hd"]


class ImageOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: ImageSize | None = None
    quality: ImageQuality | None = None
    max_prompt_characters: int = Field(default=2000, ge=1, le=2000, strict=True)


class ImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=2000)
    n: Literal[1] = 1
    size: ImageSize | None = None
    quality: ImageQuality | None = None
    response_format: Literal["b64_json"] = "b64_json"

    @field_validator("n", mode="before")
    @classmethod
    def single_image(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("每次生成 1 张图片")
        return value


class GeneratedImage(BaseModel):
    b64_json: str
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    width: int
    height: int
    bytes: int


class ImageOutput(BaseModel):
    id: str
    created: int
    data: list[GeneratedImage]
    usage: dict[str, int | None]
