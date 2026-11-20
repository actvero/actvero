"""Chat accepts image histories within the inference transport budget."""

import base64
import json

import httpx
import pytest
from fastapi import APIRouter, FastAPI
from pydantic import ValidationError

from app.modules.llm.body_limit import InferenceRoute
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


def test_inline_images_can_exceed_former_single_and_total_byte_limits():
    part = image(2 * 1024 * 1024)
    assert len(request([part] * 5).messages[0].content) == 5


@pytest.mark.asyncio
async def test_inference_route_accepts_chat_with_two_full_size_images():
    router = APIRouter(route_class=InferenceRoute)

    @router.post("/chat/completions")
    async def chat(body: ChatInput) -> dict[str, str]:
        return {"model": body.model}

    app = FastAPI()
    app.include_router(router)
    payload = {
        "model": "vision",
        "messages": [{"role": "user", "content": [image(1024 * 1024 + 1)] * 2}],
    }
    content = json.dumps(payload).encode()
    assert len(content) > 2_000_000
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/chat/completions", content=content, headers={"Content-Type": "application/json"}
        )
    assert response.status_code == 200
    assert response.json() == {"model": "vision"}


def test_image_count_follows_provider_across_history():
    part = {"type": "image_url", "image_url": {"url": "https://images.example/a.png"}}
    result = ChatInput.model_validate(
        {
            "model": "vision",
            "messages": [
                {"role": "user", "content": [part] * 16},
                {"role": "user", "content": [image(8)] * 17},
            ],
        }
    )
    assert [len(message.content) for message in result.messages] == [16, 17]


@pytest.mark.parametrize(
    "url",
    [
        "http://images.example/a.png",
        "data:image/png,plain-text",
        "data:image/png;base64,",
        "data:image/png;base64,eA",  # Missing padding.
        "data:image/png;base64,eB==",  # Noncanonical trailing bits.
        "data:image/png;base64,%%%%",
        "data:image/png;base64,eA==eA==",
    ],
)
def test_invalid_inline_data_is_rejected_without_provider_io(url):
    with pytest.raises(ValidationError):
        request([{"type": "image_url", "image_url": {"url": url}}])
