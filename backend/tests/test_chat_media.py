"""Inline images share the advertised request limits, including base64 expansion."""

import base64

import pytest
from pydantic import ValidationError

from app.modules.llm.chat_media import IMAGE_INPUT, IMAGE_URL_MAX_LENGTH
from app.modules.llm.chat_schemas import ChatInput


def image(size: int) -> dict:
    return {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64," + base64.b64encode(b"x" * size).decode()},
    }


def request(parts: list[dict]) -> ChatInput:
    return ChatInput.model_validate(
        {"model": "vision", "messages": [{"role": "user", "content": parts}]}
    )


def test_full_size_inline_images_fit_data_url_and_total_limits():
    part = image(IMAGE_INPUT.max_image_bytes)
    assert len(part["image_url"]["url"]) < IMAGE_URL_MAX_LENGTH
    assert len(request([part] * 8).messages[0].content) == 8
    with pytest.raises(ValidationError, match="单张请求图片"):
        request([image(IMAGE_INPUT.max_image_bytes + 1)])
    with pytest.raises(ValidationError, match="合计"):
        request([part] * 8 + [image(1)])


def test_images_are_counted_across_history_including_https_references():
    part = {"type": "image_url", "image_url": {"url": "https://images.example/a.png"}}
    request([part] * IMAGE_INPUT.max_images)
    with pytest.raises(ValidationError, match="32 张"):
        ChatInput.model_validate(
            {
                "model": "vision",
                "messages": [
                    {"role": "user", "content": [part] * 16},
                    {"role": "user", "content": [part] * 17},
                ],
            }
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://images.example/a.png",
        "data:image/png,plain-text",
        "data:image/png;base64,",
        "data:image/png;base64,eA",  # Missing padding.
        "data:image/png;base64,eB==",  # Noncanonical trailing bits.
        "data:image/png;base64,%%%%",
    ],
)
def test_invalid_inline_data_is_rejected_without_provider_io(url):
    with pytest.raises(ValidationError):
        request([{"type": "image_url", "image_url": {"url": url}}])
