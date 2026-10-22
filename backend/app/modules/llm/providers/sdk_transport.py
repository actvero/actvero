"""Request-local SDK networking with the gateway's DNS, size and attempt boundaries."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import httpx2
from fastapi import HTTPException

from app.core.config import Settings
from app.core.http_retry import retry_after_from_headers as retry_after_from_headers
from app.core.http_retry import retry_after_seconds as retry_after_seconds
from app.core.outbound import PinnedTransport, resolve
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.providers.failure_policy import rejected
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk_meter import Meter


async def explicit_model_not_found(response: httpx2.Response) -> bool:
    """Read at most 4 KiB of JSON to recognize one machine code, never its text."""
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        return False
    mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if mime not in ("application/json", "application/problem+json"):
        return False
    claimed = response.headers.get("content-length")
    if claimed and claimed.isdecimal() and (len(claimed) > 4 or int(claimed) > 4096):
        return False
    bounded = bytearray()
    try:
        async for chunk in response.aiter_raw():
            if len(bounded) + len(chunk) > 4096:
                return False
            bounded.extend(chunk)
        data = json.loads(bounded)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    error = data.get("error")
    return isinstance(error, dict) and error.get("code") == "model_not_found"


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, response: httpx2.Response, owner: "RuntimeTransport") -> None:
        self.response, self.owner = response, owner

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.response.aiter_raw():
                # LiteLLM is the sole owner of provider stream parsing.  The
                # meter only observes raw bytes for optional usage evidence;
                # an unsupported provider event must not abort a valid stream.
                try:
                    self.owner.meter.feed(chunk)
                except Exception as exc:
                    self.owner.meter.disable_observation(exc)
                yield chunk
        except Exception as exc:
            self.owner.failed(exc)
            raise

    async def aclose(self) -> None:
        await self.response.aclose()


class RuntimeTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        base: str,
        key: str | None,
        settings: Settings,
        adapter: str,
        *,
        endpoint: tuple[str, str] | None = None,
        binary_audio: bool = False,
        trace: AttemptTrace | None = None,
        sdk_errors: bool = False,
        timeout: httpx.Timeout | None = None,
    ) -> None:
        self.trace = trace
        self.sdk_errors = sdk_errors
        self.timeout = timeout
        self.inner = PinnedTransport(
            base,
            lambda url: resolve(
                url, settings.llm_allowed_private_origins, dns=settings.llm_public_dns
            ),
            max_bytes=8_000_000 if binary_audio else 16_000_000,
            on_send=trace.mark_sent if trace is not None else None,
        )
        self.key = key
        self.sent = False
        self.failure: HTTPException | None = None
        self.meter = Meter(adapter, self._observe_meter if trace is not None else None)
        self.endpoint = endpoint
        self.response_body: dict[str, Any] | None = None
        self.binary_audio = binary_audio
        self.response_audio: bytes | None = None
        self.responses: list[httpx2.Response] = []

    def _observe_meter(self, usage: dict[str, Any], finished: bool) -> None:
        if self.trace is None:
            return
        if len(usage) > 1:
            self.trace.observe_usage(usage, phase="terminal" if finished else "partial")
        if finished:
            self.trace.mark_upstream_terminal()

    def failed(self, exc: Exception) -> None:
        if self.failure is not None:
            return
        if isinstance(exc, HTTPException):
            self.failure = (
                UpstreamFailure(
                    502,
                    "audio_delivery_failed",
                    "上游音频超过大小限制",
                    uncertain=True,
                    health_failure=False,
                )
                if self.binary_audio
                and exc.status_code == 502
                and not isinstance(exc, UpstreamFailure)
                else exc
            )
        elif isinstance(exc, httpx2.ConnectTimeout) and self.timeout is not None:
            self.failure = UpstreamFailure(
                504, "upstream_connect_timeout", "连接模型供应商超时", retryable=True
            )
        elif isinstance(exc, (httpx2.ConnectError, httpx2.ConnectTimeout)):
            self.failure = UpstreamFailure(
                502, "upstream_unavailable", "无法连接上游", retryable=True
            )
        elif isinstance(exc, (TimeoutError, httpx2.TimeoutException)):
            self.failure = UpstreamFailure(
                504,
                "upstream_timeout",
                "上游请求超时，执行结果未确认",
                retryable=True,
                uncertain=True,
            )
        else:
            self.failure = UpstreamFailure(
                502,
                "invalid_upstream_response",
                "上游响应中断或格式无效，执行结果未确认",
                uncertain=self.sent,
            )
        if self.trace is not None:
            if self.trace.sent is None:
                self.trace.mark_not_sent()
            self.trace.note_error(self.failure)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            if self.sent or request.method != "POST":
                raise UpstreamFailure(
                    502,
                    "unexpected_sdk_request",
                    "SDK 尝试了未允许的额外请求",
                    uncertain=self.sent,
                    health_failure=False,
                )
            url = str(request.url)
            if self.endpoint is not None:
                expected, target = self.endpoint
                if request.url != httpx.URL(expected):
                    raise UpstreamFailure(
                        502,
                        "unexpected_sdk_request",
                        "SDK 请求地址与操作不符",
                        health_failure=False,
                    )
                url = target
            self.sent = True
            headers = dict(request.headers)
            headers["accept-encoding"] = "identity"
            if self.key is None:
                headers.pop("authorization", None)
            forwarded = httpx2.Request(
                request.method,
                url,
                headers=headers,
                content=await request.aread(),
                extensions={
                    **request.extensions,
                    **({"timeout": self.timeout.as_dict()} if self.timeout is not None else {}),
                },
            )
            response = await self.inner.handle_async_request(forwarded)
            self.responses.append(response)
            status = response.status_code
            if self.trace is not None:
                self.trace.note_upstream_status(status)
                if status == 429:
                    self.trace.note_retry_after_seconds(retry_after_from_headers(response.headers))
            if status != 200:
                # The response status is an explicit upstream rejection signal;
                # receiving it is not proof that the request was unbilled.
                if self.trace is not None:
                    self.trace.mark_upstream_terminal()
                if self.sdk_errors:
                    # The Router needs the real HTTP status and Retry-After to
                    # apply its own exception mapping, retry and cooldown policy.
                    failure = rejected(
                        status,
                        retry_after=retry_after_from_headers(response.headers)
                        if status == 429
                        else None,
                    )
                    self.failure = failure
                    if self.trace is not None:
                        self.trace.note_error(failure)
                    return httpx.Response(
                        status,
                        headers=response.headers.raw,
                        content=await response.aread(),
                        request=request,
                    )
                model_not_found = (
                    await explicit_model_not_found(response) if status in (403, 404) else False
                )
                raise rejected(
                    status,
                    model_not_found=model_not_found,
                    retry_after=retry_after_from_headers(response.headers)
                    if status == 429
                    else None,
                )
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ValueError("Unexpected compression")
            if self.binary_audio:
                self.response_audio = await response.aread()
                if self.trace is not None:
                    self.trace.mark_upstream_terminal()
                return httpx.Response(
                    status,
                    headers=response.headers.raw,
                    content=self.response_audio,
                    request=request,
                )
            if "text/event-stream" in response.headers.get("content-type", ""):
                return httpx.Response(
                    status,
                    headers=response.headers.raw,
                    stream=ResponseStream(response, self),
                    request=request,
                )
            content = await response.aread()
            if self.trace is not None:
                self.trace.mark_upstream_terminal()
            try:
                value = json.loads(content)
                if not isinstance(value, dict):
                    raise ValueError("Not an observable JSON object")
                self.response_body = value
                self.meter.observe(value, stream=False)
            except Exception as exc:
                # LiteLLM remains responsible for validating and converting
                # the provider response; usage observation is best effort.
                self.meter.disable_observation(exc)
            return httpx.Response(
                status, headers=response.headers.raw, content=content, request=request
            )
        except Exception as exc:
            self.failed(exc)
            raise

    async def aclose(self) -> None:
        for response in self.responses:
            await response.aclose()
        await self.inner.aclose()
