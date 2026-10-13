"""A browser batch is bounded single diagnostics, never a second backend job."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from test_diagnostics_api import chat_body
from test_identity_access import env as identity_env
from test_llm_channels import create as create_channel
from test_mcp import listening

from app.modules.auth.models import RateLimit
from app.modules.llm import channel_testing
from app.modules.llm.models import ModelCall, ModelChannel
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.providers.sdk_transport import retry_after_seconds
from app.modules.members.models import Membership

env = identity_env


@pytest.mark.parametrize(
    ("value", "server_date", "expected"),
    [
        ("7201", None, 7201),
        (
            "Wed, 21 Oct 2015 09:28:00 GMT",
            "Wed, 21 Oct 2015 07:28:00 GMT",
            7200,
        ),
        ("-1", None, None),
        ("junk", None, None),
        (None, None, None),
        ("9007199254740992", None, None),
    ],
)
def test_retry_after_parser_keeps_safe_seconds_and_server_clock(value, server_date, expected):
    received_at = datetime(2026, 10, 4, tzinfo=UTC)
    assert retry_after_seconds(value, server_date, received_at=received_at) == expected


def test_only_a_429_can_carry_retry_after_in_attempt_snapshot():
    trace = AttemptTrace()
    trace.note_upstream_status(429)
    trace.note_retry_after_seconds(7201)
    assert trace.snapshot()["retry_after_seconds"] == 7201
    trace.note_upstream_status(503)
    assert trace.snapshot()["retry_after_seconds"] is None
    trace.note_retry_after_seconds(7201)
    assert trace.snapshot()["retry_after_seconds"] is None


@pytest.mark.asyncio
async def test_real_sdk_upstream_retry_after_is_persisted_without_second_send(env):
    admin = await env.client()
    upstream, calls = FastAPI(), []
    date_deadline = format_datetime(datetime.now(UTC) + timedelta(seconds=7200), usegmt=True)
    cases = [
        (429, "7201", None, 7201),
        (429, date_deadline, None, "date"),
        (429, "invalid", None, None),
        (503, "9000", None, None),
    ]

    @upstream.post("/{path:path}")
    async def reject(path: str, request: Request):
        calls.append((path, await request.json()))
        status, retry, date, _ = cases[len(calls) - 1]
        headers = {"Retry-After": retry}
        if date is not None:
            headers["Date"] = date
        return JSONResponse(
            {"error": {"message": "test upstream rejection"}}, status_code=status, headers=headers
        )

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            base_url=root + "/v1",
            api_key="fake-key",
            models=[{"id": "test-model"}],
            declared_apis=["chat_completions"],
        )
        path = f"/api/v1/llm/channels/{channel['id']}/diagnostics"
        for index, (status, _, _, expected) in enumerate(cases, 1):
            request_id = str(uuid4())
            response = await admin.api.post(path, json=chat_body(channel["version"], request_id))
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["ok"] is False
            assert data["attempt"]["upstream_status"] == status
            actual = data["attempt"]["retry_after_seconds"]
            if expected == "date":
                assert 7190 <= actual <= 7200
            else:
                assert actual == expected
            detail = await admin.api.get(f"/api/v1/llm/diagnostics/{request_id}")
            assert detail.status_code == 200
            assert detail.json()["record"]["attempt"]["retry_after_seconds"] == actual
            assert len(calls) == index


@pytest.mark.asyncio
async def test_ten_single_item_admissions_then_429_before_dispatch_or_call(env):
    admin = await env.client()
    upstream, calls = FastAPI(), []

    @upstream.post("/{path:path}")
    async def complete(path: str, request: Request):
        calls.append((path, await request.json()))
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"},
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            base_url=root + "/v1",
            api_key="fake-key",
            models=[{"id": "test-model"}],
            declared_apis=["chat_completions"],
        )
        path = f"/api/v1/llm/channels/{channel['id']}/diagnostics"
        ids = [str(uuid4()) for _ in range(11)]
        assert len(set(ids)) == 11
        for request_id in ids[:10]:
            response = await admin.api.post(path, json=chat_body(channel["version"], request_id))
            assert response.status_code == 200 and response.json()["ok"], response.text
        key = f"channel-test:{admin.tenant.id}:{admin.user.id}"
        async with env.sessions() as db:
            counter = await db.scalar(select(RateLimit).where(RateLimit.key == key))
            assert counter.count == 10
        detail = await admin.api.get(f"/api/v1/llm/diagnostics/{ids[0]}")
        history = await admin.api.get(f"/api/v1/llm/channels/{channel['id']}/tests")
        assert detail.status_code == history.status_code == 200
        assert len(history.json()) == 10
        async with env.sessions() as db:
            counter = await db.scalar(select(RateLimit).where(RateLimit.key == key))
            assert counter.count == 10
        eleventh = await admin.api.post(path, json=chat_body(channel["version"], ids[10]))
        assert eleventh.status_code == 429
        assert eleventh.headers["Retry-After"] == "60"
        assert len(calls) == 10
        async with env.sessions() as db:
            assert await db.get(ModelCall, UUID(ids[10])) is None


@pytest.mark.asyncio
async def test_member_stale_configuration_and_archive_stop_later_items_before_dispatch(env):
    admin = await env.client()
    member = await env.client(role="member", tenant=admin.tenant)
    upstream, calls = FastAPI(), []

    @upstream.post("/{path:path}")
    async def complete(path: str, request: Request):
        calls.append(path)
        await request.json()
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 1,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "ok"},
                }
            ],
        }

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            base_url=root + "/v1",
            api_key="fake-key",
            models=[{"id": "test-model"}],
            declared_apis=["chat_completions"],
        )
        channel_path = f"/api/v1/llm/channels/{channel['id']}"
        path = channel_path + "/diagnostics"
        first = await admin.api.post(path, json=chat_body(channel["version"], str(uuid4())))
        assert first.status_code == 200 and first.json()["ok"]
        member_id, stale_id, archived_id = (str(uuid4()) for _ in range(3))
        denied = await member.api.post(path, json=chat_body(channel["version"], member_id))
        assert denied.status_code == 403
        changed = await admin.api.put(
            channel_path,
            json={"version": channel["version"], "name": "Changed", "base_url": root + "/v1"},
        )
        assert changed.status_code == 200, changed.text
        stale = await admin.api.post(path, json=chat_body(channel["version"], stale_id))
        assert stale.status_code == 409
        archived = await admin.api.put(
            channel_path + "/archive",
            json={"version": changed.json()["version"], "archived": True},
        )
        assert archived.status_code == 200
        rejected = await admin.api.post(
            path, json=chat_body(archived.json()["version"], archived_id)
        )
        assert rejected.status_code == 409
        assert len(calls) == 1
        async with env.sessions() as db:
            for request_id in (member_id, stale_id, archived_id):
                assert await db.get(ModelCall, UUID(request_id)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "expected"),
    [("version", 409), ("archive", 409), ("permission", 403)],
)
async def test_limit_commit_race_rechecks_before_receipt_or_dispatch(
    env, monkeypatch, change, expected
):
    admin = await env.client()
    upstream, calls = FastAPI(), []

    @upstream.post("/{path:path}")
    async def should_not_send(path: str):
        calls.append(path)
        return {"choices": []}

    async with listening(upstream) as root:
        env.provider.settings.llm_allowed_private_origins = [root]
        channel = await create_channel(
            admin,
            base_url=root + "/v1",
            api_key="fake-key",
            models=[{"id": "test-model"}],
            declared_apis=["chat_completions"],
        )
        original_limit = channel_testing.limit

        async def change_after_limit_commit(db, key, maximum, seconds):
            await original_limit(db, key, maximum, seconds)
            async with env.sessions() as concurrent:
                if change == "permission":
                    member = await concurrent.get(Membership, admin.member.id)
                    assert member is not None
                    member.role = "member"
                else:
                    row = await concurrent.get(ModelChannel, UUID(channel["id"]))
                    assert row is not None
                    if change == "version":
                        row.version += 1
                        row.models = []
                    else:
                        row.archived = True
                await concurrent.commit()

        monkeypatch.setattr(channel_testing, "limit", change_after_limit_commit)
        request_id = uuid4()
        response = await admin.api.post(
            f"/api/v1/llm/channels/{channel['id']}/diagnostics",
            json=chat_body(channel["version"], str(request_id)),
        )
        assert response.status_code == expected, response.text
        assert not calls
        async with env.sessions() as db:
            assert await db.get(ModelCall, request_id) is None
