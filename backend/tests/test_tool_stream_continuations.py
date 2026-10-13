"""Qwen-compatible tool continuations through the real SDK and desktop gateway."""

import json

import pytest
from llm_billing_helpers import billing
from test_desktop import bearer, native_client
from test_identity_access import env as identity_env
from test_llm_execution import BASE, GATEWAY, configured, credentials, entries, payload, upstream
from test_mcp import listening

from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.providers.chat import StreamState
from app.modules.llm.providers.sdk import litellm

env = identity_env


def chunk(call=None, finish=None):
    return {
        "choices": [
            {
                "index": 0,
                "delta": {"tool_calls": [call]} if call is not None else {},
                "finish_reason": finish,
            }
        ]
    }


@pytest.mark.parametrize("continuation_id", [None, "", "call_1"])
def test_tool_continuations_preserve_sdk_chunks(continuation_id):
    state = StreamState()
    first = chunk(
        {
            "index": 0,
            "id": "call_1",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q":'},
        }
    )
    continuation = {"index": 0, "function": {"arguments": '"ok"}'}}
    if continuation_id is not None:
        continuation["id"] = continuation_id
    second = chunk(continuation)
    for raw in (first, second, chunk(finish="tool_calls")):
        result = state.chunk(raw, "public", "request")
        assert result["choices"] == raw["choices"]
    assert state.finished


def assembled(events):
    sdk_chunks = [litellm.ModelResponse(**event, stream=True) for event in events]
    return litellm.stream_chunk_builder(sdk_chunks).choices[0].message.model_dump(exclude_none=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("continuation_id", ["", "call_1"])
async def test_desktop_tool_continuations_keep_usage_and_do_not_cool_route(
    env, monkeypatch, continuation_id
):
    admin = await env.client()
    await billing(admin)
    app, state = upstream()
    state.update(tools=True, tool_continuation_id=continuation_id)
    async with listening(app) as base:
        model, _ = await configured(env, admin, base)
        async with native_client(env) as api:
            _, token = await credentials(env, monkeypatch, api, admin, model)
            # Four successful tool streams must not trigger the three-failure circuit.
            for _ in range(4):
                result = await api.post(
                    GATEWAY,
                    headers=bearer(token),
                    json=payload(
                        model,
                        stream=True,
                        tools=[{"type": "function", "function": {"name": "lookup"}}],
                    ),
                )
                assert result.status_code == 200 and "[DONE]" in result.text, result.text
                assert '"error"' not in result.text
                events = [
                    json.loads(line[6:])
                    for line in result.text.splitlines()
                    if line.startswith("data: ") and line != "data: [DONE]"
                ]
                calls = [
                    call
                    for event in events
                    for choice in event.get("choices", [])
                    for call in choice["delta"].get("tool_calls", [])
                ]
                assert [c["id"] for c in calls if "id" in c] == ["call_1", continuation_id]
                message = assembled(events)
                assert message["tool_calls"][0]["id"] == "call_1"
                arguments = "".join(c["function"].get("arguments", "") for c in calls)
                assert json.loads(arguments) == {"q": "ok"}
                assert events[-1]["usage"]["total_tokens"] == 110
            health = (await admin.api.get(BASE + model["id"] + "/routes")).json()[0]
            assert health["failures"] == 0 and health["cooldown_until"] is None
            logs = (await admin.api.get(BASE + model["id"] + "/calls")).json()
            assert len(logs) == 4 and all(r["status"] == "succeeded" for r in logs)
            assert all(r["attempts"][0]["upstream_terminal"] for r in logs)
            ledger = await entries(admin)
            assert len(ledger) == 4
            assert all(r["status"] == "settled" and r["points"] == "0.0244" for r in ledger)

            # Return the assembled tool result and continue the conversation.
            replay = ChatInput.model_validate(
                payload(
                    model,
                    messages=[
                        {"role": "system", "content": [{"type": "text", "text": "fixture"}]},
                        {"role": "user", "content": "lookup"},
                        message,
                        {
                            "role": "tool",
                            "tool_call_id": "call_1",
                            "content": [{"type": "text", "text": "ok"}],
                        },
                    ],
                )
            )
            state["tools"] = False
            result = await api.post(
                GATEWAY, headers=bearer(token), json=replay.model_dump(exclude_none=True)
            )
            assert result.status_code == 200, result.text
            assert result.json()["choices"][0]["message"]["content"] == "answer"
            assert len(state["calls"]) == 5
