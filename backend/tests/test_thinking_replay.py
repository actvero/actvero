"""Pinned SDK signed thinking/tool replay through real local provider protocols."""

import json

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from test_mcp import listening

from app.core.config import Settings
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.providers import chat, sdk_runtime

pytestmark = pytest.mark.asyncio
SIGNATURE = "c2lnbmVkLXRoaW5raW5n" * 30  # Longer than a plain tool-call ID.


@pytest.mark.parametrize("adapter", ["anthropic", "gemini"])
@pytest.mark.parametrize("stream", [False, True])
async def test_tool_thinking_roundtrip(adapter, stream):
    app, calls = FastAPI(), []

    @app.post("/{path:path}")
    async def invoke(path: str, request: Request):
        body = await request.json()
        calls.append(body)
        if adapter == "anthropic":
            thought = {"type": "thinking", "thinking": "Need a tool", "signature": SIGNATURE}
            tool = {"type": "tool_use", "id": "tool_1", "name": "lookup", "input": {"q": "hello"}}
            raw = {
                "id": "msg_local",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [thought, tool],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
            chunks = [
                {"type": "message_start", "message": {**raw, "content": [], "stop_reason": None}},
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "thinking", "thinking": ""},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": "Need a tool"},
                },
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "signature_delta", "signature": SIGNATURE},
                },
                {"type": "content_block_stop", "index": 0},
                {"type": "content_block_start", "index": 1, "content_block": {**tool, "input": {}}},
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {"type": "input_json_delta", "partial_json": '{"q":"hello"}'},
                },
                {"type": "content_block_stop", "index": 1},
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 5},
                },
                {"type": "message_stop"},
            ]
        else:
            raw = {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {"name": "lookup", "args": {"q": "hello"}},
                                    "thoughtSignature": SIGNATURE,
                                }
                            ],
                        },
                        "index": 0,
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 5,
                    "totalTokenCount": 15,
                },
            }
            chunks = [raw]
        if not (body.get("stream") or "streamGenerateContent" in path):
            return raw

        async def events():
            for chunk in chunks:
                yield "data: " + json.dumps(chunk) + "\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    async with listening(app) as base:
        settings = Settings(_env_file=None, llm_allowed_private_origins=[base])
        model = "claude-sonnet-4-20250514" if adapter == "anthropic" else "gemini-2.5-flash"
        source = {
            "model": model,
            "messages": [{"role": "user", "content": "Look up hello"}],
            "max_tokens": 2048,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                    },
                }
            ],
            "thinking": {"type": "enabled", "budget_tokens": 1024},
            "stream": stream,
        }
        if stream:
            source["stream_options"] = {"include_usage": True}
        body = ChatInput.model_validate(source)
        if stream:
            state = chat.StreamState()
            chunks = [
                c
                async for c in sdk_runtime.events(
                    adapter, base, "test-secret", 10, settings, source, model, "local", state
                )
            ]
            message = {"role": "assistant", "content": None}
            tool_state = {}
            for chunk in chunks:
                delta = chunk["choices"][0]["delta"]
                if delta.get("thinking_blocks"):
                    message.setdefault("thinking_blocks", []).extend(delta["thinking_blocks"])
                if delta.get("reasoning_content"):
                    message["reasoning_content"] = (
                        message.get("reasoning_content", "") + delta["reasoning_content"]
                    )
                for tool in delta.get("tool_calls", []):
                    entry = tool_state.setdefault(
                        tool["index"],
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if tool.get("id"):
                        entry["id"] = tool["id"]
                    if tool.get("provider_specific_fields"):
                        entry["provider_specific_fields"] = tool["provider_specific_fields"]
                    for k in ("name", "arguments"):
                        entry["function"][k] += tool.get("function", {}).get(k, "")
            message["tool_calls"] = list(tool_state.values())
        else:
            result = await sdk_runtime.complete(adapter, base, "test-secret", 10, settings, source)
            result, _ = chat.normalize(result, body, "local")
            message = result["choices"][0]["message"]
        assert SIGNATURE in json.dumps(message)
        second = ChatInput.model_validate(
            {
                **source,
                "stream": False,
                "stream_options": None,
                "messages": source["messages"]
                + [
                    message,
                    {
                        "role": "tool",
                        "tool_call_id": message["tool_calls"][0]["id"],
                        "content": "hello result",
                    },
                ],
            }
        )
        await sdk_runtime.complete(
            adapter, base, "test-secret", 10, settings, second.model_dump(exclude_none=True)
        )
        assert len(calls) == 2
        replay = json.dumps(calls[1]["messages" if adapter == "anthropic" else "contents"])
        assert SIGNATURE in replay and "hello result" in replay
