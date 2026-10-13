"""HTTP rejection scope and Retry-After through one real SDK attempt."""

import json
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import Response
from test_mcp import listening

from app.core.config import Settings
from app.modules.llm.providers import sdk_runtime
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.providers.failure_policy import rejected
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk_transport import retry_after_seconds


def test_status_policy_is_binding_scoped_and_parameter_errors_are_not_healthy():
    auth = rejected(401)
    assert auth.auth_failure and auth.health_failure and auth.retryable
    assert not auth.binding_failure and auth.binding_failure_reason is None
    for status in (403, 404):
        generic = rejected(status)
        assert (
            generic.binding_failure and generic.binding_failure_reason == "unclassified_rejection"
        )
        assert generic.retryable and not generic.auth_failure and not generic.health_failure
        specific = rejected(status, model_not_found=True)
        assert specific.binding_failure_reason == "model_unavailable"
    for status in (400, 422):
        invalid = rejected(status)
        assert not invalid.retryable and not invalid.health_failure
        assert not invalid.auth_failure and not invalid.binding_failure
    limited = rejected(429, retry_after=7200)
    assert limited.retryable and limited.retry_after == 7200
    assert not limited.auth_failure and not limited.health_failure
    temporary = rejected(503)
    assert temporary.retryable and temporary.health_failure and not temporary.auth_failure


def test_retry_after_parser_keeps_long_wait_and_dates():
    assert retry_after_seconds("7200", None) == 7200
    assert retry_after_seconds("0", None) == 0
    assert retry_after_seconds("invalid", None) is None
    assert retry_after_seconds("9007199254740992", None) is None
    received = datetime(2030, 1, 1, tzinfo=UTC)
    assert (
        retry_after_seconds(
            "Tue, 01 Jan 2030 03:00:00 GMT",
            "Tue, 01 Jan 2030 00:00:00 GMT",
            received_at=received,
        )
        == 10800
    )
    assert retry_after_seconds("Tue, 01 Jan 2030 03:00:00 GMT", None, received_at=received) == 10800


@pytest.mark.parametrize(
    ("status", "error_code", "retry_header", "reason"),
    [
        (401, "model_not_found", None, None),
        (403, "model_not_found", None, "model_unavailable"),
        (403, "permission_denied", None, "unclassified_rejection"),
        (404, "model_not_found", None, "model_unavailable"),
        (404, "not_found", None, "unclassified_rejection"),
        (400, "model_not_found", None, None),
        (422, "invalid_request", None, None),
        (429, "rate_limit_exceeded", "7200", None),
        (429, "rate_limit_exceeded", "Tue, 01 Jan 2030 03:00:00 GMT", None),
        (429, "rate_limit_exceeded", "0", None),
        (429, "rate_limit_exceeded", "invalid", None),
        (503, "internal_error", None, None),
    ],
)
@pytest.mark.asyncio
async def test_real_sdk_rejection_is_one_send_and_exposes_only_safe_metadata(
    status, error_code, retry_header, reason
):
    upstream, calls = FastAPI(), []

    @upstream.post("/{path:path}")
    async def reply(path: str, request: Request):
        calls.append((path, await request.json()))
        headers = {"Retry-After": retry_header} if retry_header is not None else {}
        if retry_header and retry_header.startswith("Tue,"):
            headers["Date"] = "Tue, 01 Jan 2030 00:00:00 GMT"
        return Response(
            json.dumps({"error": {"code": error_code, "message": "private-upstream-secret"}}),
            status_code=status,
            media_type="application/json",
            headers=headers,
        )

    async with listening(upstream) as root:
        trace = AttemptTrace()
        settings = Settings(_env_file=None, llm_allowed_private_origins=[root])
        with pytest.raises(UpstreamFailure) as caught:
            await sdk_runtime.complete(
                "openai",
                root + "/v1",
                "fake-key",
                5,
                settings,
                {
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "private-input"}],
                    "max_tokens": 8,
                },
                trace=trace,
            )
    failure = caught.value
    assert failure.upstream_status == status
    assert failure.auth_failure is (status == 401)
    assert failure.binding_failure is (status in (403, 404))
    assert failure.binding_failure_reason == reason
    assert failure.retryable is (status in (401, 403, 404, 429, 503))
    assert failure.health_failure is (status in (401, 503))
    expected_wait = (
        7200
        if retry_header == "7200"
        else 10800
        if retry_header and retry_header.startswith("Tue,")
        else 0
        if retry_header == "0"
        else None
    )
    if retry_header and retry_header.startswith("Tue,"):
        # Uvicorn also emits its own Date; conflicting dates are resolved to
        # the longest wait so the supplier's stated deadline is never early.
        assert failure.retry_after is not None and failure.retry_after >= expected_wait
    else:
        assert failure.retry_after == expected_wait
    assert trace.snapshot()["retry_after_seconds"] == failure.retry_after
    assert trace.snapshot()["upstream_terminal"] is True
    assert trace.snapshot()["sent"] is True
    assert len(calls) == 1 and calls[0][0] == "v1/chat/completions"
    assert "private-upstream-secret" not in str(failure)
    assert "private-input" not in str(trace.snapshot())


@pytest.mark.parametrize("payload", ["malformed", "oversized", "numeric", "text"])
@pytest.mark.asyncio
async def test_untrusted_error_body_cannot_claim_model_reason(payload):
    upstream = FastAPI()

    @upstream.post("/{path:path}")
    async def reply(path: str, request: Request):
        await request.body()
        if payload == "malformed":
            return Response('{"error":', status_code=404, media_type="application/json")
        if payload == "oversized":
            return Response(
                json.dumps({"error": {"code": "model_not_found", "message": "x" * 5000}}),
                status_code=404,
                media_type="application/json",
            )
        if payload == "numeric":
            return Response(
                json.dumps({"error": {"code": 404, "message": "private"}}),
                status_code=404,
                media_type="application/json",
            )
        return Response(
            '{"error":{"code":"model_not_found"}}',
            status_code=404,
            media_type="text/plain",
        )

    async with listening(upstream) as root:
        settings = Settings(_env_file=None, llm_allowed_private_origins=[root])
        with pytest.raises(UpstreamFailure) as caught:
            await sdk_runtime.complete(
                "openai",
                root + "/v1",
                "fake-key",
                5,
                settings,
                {
                    "model": "test-model",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 8,
                },
            )
    assert caught.value.binding_failure_reason == "unclassified_rejection"
