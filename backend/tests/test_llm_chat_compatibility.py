"""Upstream tool-call shapes observed during SiliconFlow integration."""

import pytest

from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.providers.chat import normalize


def tool_response():
    return {
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_sum",
                            "type": "function",
                            "function": {"name": "add_numbers", "arguments": '{"a":2,"b":3}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 186, "completion_tokens": 29},
    }


def test_complete_tool_call_accepts_provider_index_and_can_be_returned():
    body = ChatInput(model="team-chat", messages=[{"role": "user", "content": "2 + 3"}])
    raw = tool_response()
    output, meter = normalize(raw, body, "test-call")
    message = output["choices"][0]["message"]
    call = message["tool_calls"][0]
    assert call["index"] == 0
    assert call["id"] == "call_sum"
    assert call["function"] == {"name": "add_numbers", "arguments": '{"a":2,"b":3}'}
    assert raw["choices"][0]["message"]["tool_calls"][0]["index"] == 0
    assert output["model"] == "team-chat" and meter["output_tokens"] == 29
    reply = ChatInput.model_validate(
        {
            "model": "team-chat",
            "messages": [
                *body.model_dump()["messages"],
                message,
                {"role": "tool", "tool_call_id": call["id"], "content": "5"},
            ],
        }
    )
    assert reply.messages[-1].tool_call_id == "call_sum"


@pytest.mark.parametrize("finish_reason", ["stop", "function_call", "tool_calls", "content_filter"])
def test_sdk_finish_and_provider_metadata_survive_normalization(finish_reason):
    raw = tool_response()
    raw["choices"][0]["finish_reason"] = finish_reason
    message = raw["choices"][0]["message"]
    message["provider_specific_fields"] = {"native_finish_reason": "tool_use", "future": 1}
    message["tool_calls"][0]["provider_specific_fields"] = {"thought_signature": "signed"}
    message["refusal"] = "declined" if finish_reason == "content_filter" else None
    body = ChatInput(model="team-chat", messages=[{"role": "user", "content": "2 + 3"}])
    output, _ = normalize(raw, body, "test-call")
    assert output["choices"] == raw["choices"]
    replay = ChatInput.model_validate({"model": "team-chat", "messages": [message]})
    saved = replay.messages[0].model_dump(exclude_none=True)
    assert saved["provider_specific_fields"] == message["provider_specific_fields"]
    assert saved["tool_calls"] == message["tool_calls"]
