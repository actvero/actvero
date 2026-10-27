"""One LiteLLM Router per application, with request-local credentials and evidence.

SDK public deployment hooks inject our existing pinned HTTP transport. The SDK
owns selection, weighted failover, exception mapping and cooldowns. These hooks
only enforce the authorized deployment set and collect billable attempt facts.
"""

import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import anyio
import httpx
from fastapi import HTTPException
from litellm.exceptions import BadRequestError
from litellm.integrations.custom_logger import CustomLogger
from litellm.router import Router
from litellm.types.router import Deployment, LiteLLM_Params
from openai import AsyncOpenAI

from app.core.config import Settings
from app.modules.llm.providers.attempt import AttemptTrace
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.providers.sdk import ChannelHTTPHandler, litellm
from app.modules.llm.providers.sdk_runtime import prepare_images, selected_usage
from app.modules.llm.providers.sdk_transport import RuntimeTransport
from app.modules.llm.providers.timeouts import ExecutionTimeout, Timeouts


@dataclass
class Candidate:
    identity: str
    adapter: str
    model: str
    base: str
    key: str | None
    endpoint: tuple[str, str] | None
    priority: int
    weight: int
    allowed_fails: int
    cooldown: int
    payload: dict[str, Any]
    evidence: dict[str, Any]
    allowed: bool = True
    protect: bool = True


@dataclass
class Attempt:
    candidate: Candidate
    trace: AttemptTrace
    transport: RuntimeTransport
    client: httpx.AsyncClient
    error: HTTPException | None = None

    def snapshot(self) -> dict[str, Any]:
        error = self.error or self.transport.failure
        if error is not None:
            self.trace.note_error(error)
        usage = selected_usage(self.transport.meter)
        gateway_reference = {}
        if self.candidate.evidence.get("gateway"):
            ids = {r.headers.get("X-Oneapi-Request-Id") for r in self.transport.responses}
            ids.discard(None)
            if len(ids) == 1:
                request_id = next(iter(ids))
                if request_id and len(request_id) <= 128 and request_id.isalnum():
                    gateway_reference = {"gateway_request_id": request_id}
        return {
            **self.candidate.evidence,
            **gateway_reference,
            **self.trace.snapshot(),
            "status": "failed" if error else "succeeded",
            "usage": usage,
            "error_code": getattr(error, "code", "upstream_error")
            if error
            else self.trace.error_code,
        }


_current: ContextVar["Invocation | None"] = ContextVar("actvero_sdk_invocation", default=None)


class OwnedRouter(Router):
    """Scope SDK global callbacks to deployments owned by this application.

    Do not reset or remove callbacks owned by other SDK consumers. All routing
    and cooldown decisions still run in the pinned SDK implementation.
    """

    def __init__(self, **kwargs: Any) -> None:
        self.owned_ids: set[str] = set()
        self.evidence: dict[str, tuple[AttemptTrace, bool, float]] = {}
        super().__init__(**kwargs)

    def owns(self, kwargs: dict[str, Any]) -> bool:
        return (kwargs.get("litellm_params", {}).get("model_info") or {}).get(
            "id"
        ) in self.owned_ids

    async def make_call(self, original_function: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return await super().make_call(original_function, *args, **kwargs)
        except Exception as exc:
            # SDK 1.102.1's non-chat entries stamp retry_skip_deployment_id,
            # whereas its weighted failover reads failed_deployment_id. Bridge
            # only these SDK-owned identities; selection/retries remain SDK code.
            identity = getattr(exc, "retry_skip_deployment_id", None)
            if identity in self.owned_ids and not getattr(exc, "failed_deployment_id", None):
                exc.failed_deployment_id = identity  # type: ignore[attr-defined]
            raise

    def owns_failure(self, kwargs: dict[str, Any]) -> bool:
        if not self.owns(kwargs):
            return False
        metadata = kwargs.get("litellm_params", {}).get("metadata") or {}
        entry = self.evidence.get(str(metadata.get("actvero_attempt_id", "")))
        if entry is None:
            return False
        trace, protect, _ = entry
        if not protect and trace.upstream_status not in {401, 429}:
            return False
        if trace.error_scope in {"sdk", "delivery", "preflight", "client"} or trace.sent is False:
            return False
        # Only transport/HTTP failures substantiate provider health changes.
        return trace.upstream_status != 200

    async def deployment_callback_on_success(self, kwargs: Any, *args: Any) -> None:
        if self.owns(kwargs):
            await super().deployment_callback_on_success(kwargs, *args)  # type: ignore[no-untyped-call]

    def sync_deployment_callback_on_success(self, kwargs: Any, *args: Any) -> None:
        if self.owns(kwargs):
            super().sync_deployment_callback_on_success(kwargs, *args)

    def deployment_callback_on_failure(self, kwargs: Any, *args: Any) -> bool:
        if self.owns_failure(kwargs):
            # Our configured fallback wait must not override an upstream 429
            # Retry-After. Remove that one override from the callback snapshot;
            # the SDK still parses the header and owns the resulting cache TTL.
            params = kwargs.get("litellm_params", {})
            entry = self.evidence.get(
                str((params.get("metadata") or {}).get("actvero_attempt_id", ""))
            )
            if entry and entry[0].retry_after_seconds is not None:
                params = dict(params)
                params.pop("cooldown_time", None)
                params["model_info"] = {
                    k: v
                    for k, v in (params.get("model_info") or {}).items()
                    if k != "cooldown_time"
                }
                kwargs = dict(kwargs, litellm_params=params)
            return super().deployment_callback_on_failure(kwargs, *args)
        return False

    async def async_deployment_callback_on_failure(self, kwargs: Any, *args: Any) -> None:
        if self.owns_failure(kwargs):
            await super().async_deployment_callback_on_failure(kwargs, *args)


class RequestHook(CustomLogger):
    def __init__(self, owner: "Gateway") -> None:
        self.owner = owner
        super().__init__()

    def invocation(self) -> "Invocation | None":
        invocation = _current.get()
        return invocation if invocation and invocation.gateway is self.owner else None

    async def async_filter_deployments(
        self,
        model: str,
        healthy_deployments: list[Any],
        messages: Any,
        request_kwargs: Any = None,
        parent_otel_span: Any = None,
    ) -> list[Any]:
        invocation = self.invocation()
        if invocation is None:
            return healthy_deployments
        return [d for d in healthy_deployments if invocation.allowed(d["model_info"]["id"])]

    async def async_pre_call_deployment_hook(self, kwargs: dict[str, Any], call_type: Any) -> Any:
        invocation = self.invocation()
        if invocation is None:
            return None
        identity = (kwargs.get("model_info") or {}).get("id")
        if not invocation.allowed(identity):
            raise BadRequestError("Deployment is not authorized", model="", llm_provider="")
        assert isinstance(identity, str)
        return await invocation.prepare(identity, kwargs)

    async def async_post_call_failure_deployment_hook(
        self,
        request_data: Mapping[str, object],
        exception: Exception,
        call_type: Any,
        fallback_depth: int | None = None,
    ) -> None:
        invocation = self.invocation()
        if invocation and invocation.attempts:
            invocation.attempts[-1].error = invocation.failure(exception)


class Gateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.router = OwnedRouter(
            model_list=[],
            num_retries=0,
            max_fallbacks=0,
            enable_weighted_failover=True,
            enable_pre_call_checks=False,
            cache_responses=False,
            debug_level="ERROR",
            redis_url=settings.llm_router_redis_url.get_secret_value()
            if settings.llm_router_redis_url
            else None,
        )
        self.hook = RequestHook(self)
        litellm.callbacks.append(self.hook)
        self.groups: dict[str, float] = {}
        self.active: dict[str, int] = {}

    def register(self, candidates: list[Candidate]) -> tuple[str, dict[str, Candidate]]:
        digest = hashlib.sha256(
            json.dumps(sorted(c.identity for c in candidates)).encode()
        ).hexdigest()
        group = "actvero-" + digest
        indexed = {group + "-" + c.identity: c for c in candidates}
        if group not in self.groups:
            for identity, c in indexed.items():
                # Credentials/clients are injected only inside the request hook.
                self.router.add_deployment(
                    Deployment(
                        model_name=group,
                        litellm_params=LiteLLM_Params(
                            **{
                                "model": f"{c.adapter}/{c.model}",
                                "api_key": "actvero-request-local",
                                "api_base": c.base,
                                "order": -c.priority,
                                "weight": c.weight,
                                "max_retries": 0,
                            }
                        ),
                        model_info={
                            "id": identity,
                            "allowed_fails": c.allowed_fails,
                            "allowed_fails_policy": {
                                "AuthenticationErrorAllowedFails": 0,
                                "RateLimitErrorAllowedFails": 0,
                            },
                            "cooldown_time": c.cooldown,
                        },
                    )
                )
                self.router.owned_ids.add(identity)
        self.groups[group] = time.monotonic()
        self.active[group] = self.active.get(group, 0) + 1
        # Retain SDK cooldowns across requests; prune unused config generations.
        for old, touched in list(self.groups.items()):
            if self.active.get(old, 0) == 0 and time.monotonic() - touched > 3600:
                for deployment in self.router.get_model_list(model_name=old) or []:
                    identity = deployment["model_info"]["id"]
                    self.router.delete_deployment(id=identity)
                    self.router.owned_ids.discard(identity)
                self.groups.pop(old)
                self.active.pop(old, None)
        return group, indexed

    def close(self) -> None:
        self.router.discard()  # type: ignore[no-untyped-call]
        if self.hook in litellm.callbacks:
            litellm.callbacks.remove(self.hook)


class Invocation:
    def __init__(
        self,
        gateway: Gateway,
        candidates: list[Candidate],
        *,
        operation: str,
        max_attempts: int,
        timeout: float,
        connect_timeout: float,
        first_response_timeout: float,
        stream_idle_timeout: float,
        retry_uncertain: bool,
        checkpoint: Callable[[list[dict[str, Any]]], Awaitable[None]],
        authorize_next: Callable[[Candidate], Awaitable[None]],
    ) -> None:
        self.gateway, self.operation = gateway, operation
        self.group, self.candidates = gateway.register(candidates)
        self.payload_fields = set().union(*(c.payload.keys() for c in candidates))
        self.maximum, self.retry_uncertain = max_attempts, retry_uncertain
        self.timeouts = Timeouts(timeout, first_response_timeout, stream_idle_timeout)
        self.connect_timeout = connect_timeout
        self.received_chunk = False
        self.checkpoint = checkpoint
        self.authorize_next = authorize_next
        self.attempts: list[Attempt] = []

    def allowed(self, identity: Any) -> bool:
        candidate = self.candidates.get(identity)
        return candidate is not None and candidate.allowed

    async def prepare(self, identity: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        candidate = self.candidates[identity]
        await self.authorize_next(candidate)
        if len(self.attempts) >= self.maximum:
            raise BadRequestError("Attempt budget exhausted", model=self.group, llm_provider="")
        if self.attempts and not self.retry_uncertain:
            previous = self.attempts[-1]
            # Monetary policy: do not pay for another execution when the first
            # may have run without an explicit HTTP rejection.
            if previous.trace.sent and (previous.trace.upstream_status in (None, 200)):
                raise BadRequestError(
                    "Unconfirmed execution cannot be repeated", model=self.group, llm_provider=""
                )
        trace = AttemptTrace()
        # Model execution has its own policy. The channel's directory/diagnostic
        # timeout must not silently impose another short limit on live output.
        timeout = httpx.Timeout(
            self.timeouts.remaining(), connect=self.connect_timeout, pool=self.connect_timeout
        )
        transport = RuntimeTransport(
            candidate.base,
            candidate.key,
            self.gateway.settings,
            candidate.adapter,
            endpoint=candidate.endpoint,
            binary_audio=self.operation == "speech",
            trace=trace,
            sdk_errors=True,
            timeout=timeout,
        )
        http = httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=timeout,
        )
        client = (
            AsyncOpenAI(
                api_key=candidate.key or "unused-no-auth",
                base_url=candidate.base,
                http_client=http,
                max_retries=0,
            )
            if candidate.adapter == "openai"
            else ChannelHTTPHandler(http)
        )
        attempt = Attempt(candidate, trace, transport, http)
        self.attempts.append(attempt)
        self.gateway.router.evidence[trace.attempt_id] = trace, candidate.protect, time.monotonic()
        evidence = self.gateway.router.evidence
        while evidence:
            key = next(iter(evidence))
            if time.monotonic() - evidence[key][2] <= 300 and len(evidence) <= 10000:
                break
            evidence.pop(key)
        # Mutate the existing metadata dictionary so the SDK logging context
        # observes only this non-secret identity, even in delayed callbacks.
        kwargs.setdefault("metadata", {})["actvero_attempt_id"] = trace.attempt_id
        if self.operation == "chat":
            await prepare_images(candidate.payload, self.gateway.settings)
        pending = self.snapshots()
        pending[-1]["status"] = "pending"
        await self.checkpoint(pending)  # Durable dispatch intent before any network send.
        return {
            **{k: v for k, v in kwargs.items() if k not in self.payload_fields},
            **candidate.payload,
            "model": f"{candidate.adapter}/{candidate.model}"
            if self.operation in {"speech", "transcription", "image_generation"}
            else candidate.model,
            "custom_llm_provider": candidate.adapter,
            "api_base": candidate.base,
            "api_key": candidate.key or "unused-no-auth",
            "client": client,
            "num_retries": 0,
            "max_retries": 0,
            "caching": False,
            "drop_params": False,
            "timeout": self.timeouts.remaining(),
            "stream_timeout": self.timeouts.remaining(),
        }

    def snapshots(self) -> list[dict[str, Any]]:
        return [dict(a.snapshot(), number=i + 1) for i, a in enumerate(self.attempts)]

    def failure(self, exc: Exception) -> HTTPException:
        if isinstance(exc, ExecutionTimeout):
            return UpstreamFailure(
                504,
                exc.code,
                exc.message,
                uncertain=bool(self.attempts and self.attempts[-1].trace.sent),
                health_failure=False,
            )
        if self.attempts and self.attempts[-1].transport.failure is not None:
            return self.attempts[-1].transport.failure
        if isinstance(exc, HTTPException):
            return exc
        if self.attempts and not self.attempts[-1].transport.sent:
            self.attempts[-1].trace.mark_not_sent()
        sent = bool(self.attempts and self.attempts[-1].trace.sent)
        if isinstance(exc, TimeoutError) or type(exc).__name__ == "Timeout":
            return UpstreamFailure(
                504, "upstream_timeout", "模型调用超时", uncertain=sent, health_failure=False
            )
        if getattr(exc, "status_code", None) == 429 or "RateLimit" in type(exc).__name__:
            return UpstreamFailure(
                429, "sdk_route_wait", "SDK 暂时没有可用渠道，请稍后重试", health_failure=False
            )
        return UpstreamFailure(
            502 if sent else 422,
            "sdk_response_error" if sent else "unsupported_sdk_parameters",
            "SDK 未能完成模型调用",
            uncertain=sent,
            health_failure=False,
        )

    async def call(self, payload: dict[str, Any]) -> Any:
        method = {
            "chat": "acompletion",
            "embedding": "aembedding",
            "rerank": "arerank",
            "image_generation": "aimage_generation",
            "speech": "aspeech",
            "transcription": "atranscription",
        }[self.operation]
        token = _current.set(self)
        try:
            async with self.timeouts.waiting(first=True):
                return await getattr(self.gateway.router, method)(
                    **{
                        **payload,
                        "model": self.group,
                        "num_retries": 0,
                        "max_fallbacks": self.maximum - 1,
                        "caching": False,
                    },
                )
        except Exception as exc:
            error = self.failure(exc)
            if self.attempts:
                self.attempts[-1].error = error
            raise error from None
        finally:
            _current.reset(token)

    async def next(self, stream: Any) -> Any:
        # StreamingResponse may resume in a different task. Bind context for
        # each SDK await, never hold a ContextVar token across an application yield.
        token = _current.set(self)
        try:
            async with self.timeouts.waiting(first=not self.received_chunk):
                chunk = await anext(stream)
            self.received_chunk = True
            return chunk
        except StopAsyncIteration:
            raise
        except Exception as exc:
            error = self.failure(exc)
            if self.attempts:
                self.attempts[-1].error = error
            raise error from None
        finally:
            _current.reset(token)

    async def close(self) -> None:
        self.gateway.active[self.group] -= 1
        with anyio.move_on_after(3, shield=True):
            for attempt in self.attempts:
                await attempt.client.aclose()
