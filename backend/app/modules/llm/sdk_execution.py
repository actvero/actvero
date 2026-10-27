"""Admitted model execution: SDK routing and a durable accounting handoff."""

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

import anyio
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import now, provider
from app.modules.desktop.errors import fail
from app.modules.llm import routing
from app.modules.llm.audio_delivery import deliver_audio
from app.modules.llm.audio_schemas import SpeechInput, TranscriptionInput, TranscriptSegment
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.image_delivery import deliver_image
from app.modules.llm.image_schemas import ImageInput
from app.modules.llm.inference_schemas import (
    EmbeddingInput,
    EmbeddingOutput,
    RerankInput,
    RerankOutput,
)
from app.modules.llm.models import ModelCall, ModelChannel
from app.modules.llm.providers import PROVIDERS, chat, retrieval, sdk_images, sdk_speech
from app.modules.llm.providers.connection import resolve_stored_connection
from app.modules.llm.providers.sdk_router import Candidate, Gateway, Invocation
from app.modules.llm.providers.sdk_runtime import selected_usage

Body = ChatInput | EmbeddingInput | RerankInput | ImageInput | SpeechInput | TranscriptionInput


def candidates(
    request: Request,
    tenant_id: UUID,
    model_id: UUID,
    version: int,
    config: CatalogInput,
    channels: dict[UUID, ModelChannel],
    body: Body,
    specific: tuple[UUID, str] | None,
) -> list[Candidate]:
    from app.modules.llm.chat_policy import supports

    result = []
    for binding in config.bindings:
        pair = binding.channel_id, binding.upstream_id
        if specific and pair != specific:
            continue
        if (
            not specific
            and config.routing.mode == "fixed"
            and pair != (config.access.channel_id, config.access.upstream_id)
        ):
            continue
        channel = channels.get(binding.channel_id)
        if not routing.available(
            config,
            binding,
            channel,
            allow_disabled=bool(specific),
            ignore_manual_enabled=bool(specific),
        ):
            continue
        assert channel is not None
        adapter = PROVIDERS[channel.provider].sdk_provider
        base = channel.base_url
        path = {
            "chat": "/chat/completions",
            "embedding": "/embeddings",
            "rerank": "/rerank",
            "image_generation": "/images/generations",
            "speech": "/audio/speech",
            "transcription": "/audio/transcriptions",
        }[config.kind]
        endpoint = (base.rstrip("/") + path, base.rstrip("/") + path)
        if config.kind == "rerank":
            adapter = "cohere"
            endpoint = (base.rstrip("/") + "/v1/rerank", base.rstrip("/") + path)
            base = endpoint[0]
        if channel.connection:
            target = resolve_stored_connection(
                channel.provider,
                channel.base_url,
                channel.connection,
                model=binding.upstream_id,
                operations=(config.kind,),
                stream=isinstance(body, ChatInput) and body.stream,
            ).operation_targets[0]
            adapter, base = target.sdk_provider, target.sdk_api_base
            endpoint = target.sdk_expected_url, target.url
        payload: dict[str, Any]
        if isinstance(body, ChatInput):
            payload = chat.prepare(body, config, binding, adapter)
        elif isinstance(body, SpeechInput):
            probe = sdk_speech.prepare(body, config.speech, binding.upstream_id)
            payload = {"input": probe.input, "voice": probe.voice, "response_format": "wav"}
        elif isinstance(body, ImageInput):
            image_probe = sdk_images.prepare(body, config.image, binding.upstream_id)
            payload = {
                "prompt": image_probe.prompt,
                "n": 1,
                **image_probe.model_dump(include={"size", "quality"}, exclude_none=True),
            }
        elif isinstance(body, TranscriptionInput):
            payload = {
                "file": ("audio.wav", body.audio, "audio/wav"),
                "response_format": body.response_format,
            }
            if body.language:
                payload["language"] = body.language
            if body.response_format == "verbose_json":
                payload["timestamp_granularities"] = ["segment"]
        else:
            _, payload, _ = retrieval.prepare(body, config.retrieval, binding.upstream_id)
            if isinstance(body, EmbeddingInput):
                payload["allowed_openai_params"] = ["dimensions"]
            else:
                payload["return_documents"] = False
        prices = {
            "budget": config.budget_price.model_dump(mode="json") if config.budget_price else None,
            "procurement": binding.price.model_dump(mode="json") if binding.price else None,
        }
        identity = routing.hash_value(
            [
                tenant_id,
                model_id,
                version,
                config.kind,
                binding.model_dump(mode="json"),
                routing.fingerprint(config, binding, channel),
            ]
        )
        result.append(
            Candidate(
                identity=identity,
                adapter=adapter,
                model=binding.upstream_id,
                base=base,
                key=str(provider(request).unseal(channel.sealed_key)["key"])
                if channel.sealed_key and channel.auth_mode == "api_key"
                else None,
                endpoint=endpoint,
                priority=binding.priority,
                weight=binding.weight,
                allowed_fails=config.routing.failure_threshold,
                cooldown=config.routing.cooldown_seconds,
                protect=(channel.automatic_protection or {}).get("enabled", True),
                payload=payload,
                allowed=not isinstance(body, ChatInput) or supports(body, config, binding, channel),
                evidence={
                    "binding_id": str(binding.binding_id) if binding.binding_id else None,
                    "operation": config.kind,
                    "config_version": version,
                    "channel_id": str(channel.id),
                    "channel_name": channel.name,
                    "upstream_id": binding.upstream_id,
                    "channel_version": channel.version,
                    "priority": binding.priority,
                    "weight": binding.weight,
                    "prices": prices,
                    "started_at": now().isoformat(),
                    "retry_reason": None,
                    "estimates": {},
                },
            )
        )
    if not any(c.allowed for c in result):
        fail(409, "route_unavailable", "没有已启用且获准调用的渠道，请检查渠道绑定与业务参数限制")
    return result


class AccessWatch:
    """Known revocation stops delivery; edits use the admitted snapshot.

    Checks use independent sessions and never hold up chunks. A database outage
    cannot revoke an already-admitted request; admission itself remains fail-closed.
    """

    def __init__(
        self, request: Request, model_id: UUID, version: int, test: bool, kind: Any
    ) -> None:
        self.request, self.model_id, self.version, self.test, self.kind = (
            request,
            model_id,
            version,
            test,
            kind,
        )
        self.channel: tuple[UUID, int] | None = None
        self.binding_id: UUID | None = None
        self.error: HTTPException | None = None
        self.task = asyncio.create_task(self.run())

    async def check(self) -> None:
        from app.modules.llm.runtime import check_live

        if self.channel is None:
            return
        try:
            async with asyncio.timeout(0.25):
                async with self.request.app.state.database.sessions() as db:
                    await check_live(
                        self.request,
                        db,
                        self.model_id,
                        self.version,
                        *self.channel,
                        self.test,
                        self.kind,
                        binding_id=self.binding_id,
                    )
        except HTTPException as exc:
            self.error = exc
        except Exception:
            # No authorization result was obtained. Keep the admission snapshot;
            # retry in the background, without coupling output to DB availability.
            pass

    async def run(self) -> None:
        while True:
            await self.check()
            await asyncio.sleep(1)

    def enforce(self) -> None:
        if self.error:
            raise self.error

    async def close(self) -> None:
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def execute(
    request: Request,
    db: AsyncSession,
    log: ModelCall,
    config: CatalogInput,
    body: Body,
    pool: list[Candidate],
    *,
    test: bool,
) -> AsyncGenerator[EmbeddingOutput | RerankOutput | dict[str, Any]]:
    from app.modules.llm.runtime import valuation

    settings = provider(request).settings
    if request.app.state.llm_gateway is None:
        request.app.state.llm_gateway = Gateway(settings)
    outbox = request.app.state.llm_outbox
    started = time.monotonic()
    record = {
        "call_id": str(log.id),
        "tenant_id": str(log.tenant_id),
        "complete": False,
        "expires_at": time.time() + config.routing.total_timeout_seconds + 30,
        "attempts": [],
        "status": "pending",
        "delivered": False,
        "usage": {},
        "estimates": {},
    }
    assert log.model_id is not None
    watch = AccessWatch(
        request, log.model_id, pool[0].evidence["config_version"], test, config.kind
    )

    async def checkpoint(attempts: list[dict[str, Any]]) -> None:
        watch.enforce()
        last = attempts[-1]
        watch.channel = UUID(last["channel_id"]), last["channel_version"]
        record["attempts"] = attempts
        try:
            await outbox.checkpoint(record, required=True)
        except OSError:
            fail(503, "accounting_unavailable", "调用凭证暂时无法持久保存，请稍后重试")

    async def authorize_next(candidate: Candidate) -> None:
        watch.channel = (
            UUID(candidate.evidence["channel_id"]),
            candidate.evidence["channel_version"],
        )
        identity = candidate.evidence["binding_id"]
        watch.binding_id = UUID(identity) if identity else None
        await watch.check()
        watch.enforce()

    invocation = Invocation(
        request.app.state.llm_gateway,
        pool,
        operation=config.kind,
        max_attempts=config.routing.max_attempts
        if config.routing.mode == "auto" and config.routing.fallback
        else 1,
        timeout=config.routing.total_timeout_seconds,
        connect_timeout=config.routing.connect_timeout_seconds,
        first_response_timeout=config.routing.first_response_timeout_seconds,
        stream_idle_timeout=config.routing.stream_idle_timeout_seconds,
        retry_uncertain=config.routing.retry_uncertain,
        checkpoint=checkpoint,
        authorize_next=authorize_next,
    )
    stream = None
    result_ready = False
    error: BaseException | None = None
    usage: dict[str, Any] = {}
    output: EmbeddingOutput | RerankOutput | dict[str, Any] | None = None
    try:
        response = await invocation.call(next(c.payload for c in pool if c.allowed))
        attempt = invocation.attempts[-1]
        if isinstance(body, ChatInput) and body.stream:
            stream = response
            state = chat.StreamState()
            while True:
                try:
                    chunk = await invocation.next(stream)
                except StopAsyncIteration:
                    break
                attempt = invocation.attempts[-1]
                watch.channel = (
                    UUID(attempt.candidate.evidence["channel_id"]),
                    attempt.candidate.evidence["channel_version"],
                )
                watch.enforce()
                raw = chunk.model_dump(exclude_none=True)
                raw.pop("usage", None)
                event = state.chunk(raw, body.model, str(log.id))
                if event is not None:
                    attempt.trace.mark_output()
                    yield event
            usage = selected_usage(attempt.transport.meter)
            output = {
                "id": "chatcmpl-" + str(log.id),
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": body.model,
                "choices": [],
                "usage": chat.public_usage(usage),
            }
        elif isinstance(body, ChatInput):
            raw = response.model_dump(exclude_none=True)
            raw["usage"] = (
                attempt.transport.meter.openai_usage()
                if selected_usage(attempt.transport.meter).get("source") == "upstream"
                else None
            )
            output, usage = chat.normalize(raw, body, str(log.id))
        elif isinstance(body, (EmbeddingInput, RerankInput)):
            raw = response.model_dump(exclude_none=True)
            original = attempt.transport.response_body or {}
            raw.update(usage=original.get("usage"), meta=original.get("meta"))
            output, usage = retrieval.normalize(raw, body, config.retrieval, str(log.id))
            _, _, characters = retrieval.prepare(body, config.retrieval, attempt.candidate.model)
            usage["input_characters"] = characters
            attempt.trace.observe_usage(usage)
            attempt.trace.observe_usage({"input_characters": characters}, phase="validated_input")
        elif isinstance(body, ImageInput):
            data = response.model_dump(exclude_none=True).get("data")
            if not isinstance(data, list) or len(data) != 1:
                raise retrieval.UpstreamFailure(
                    502,
                    "image_delivery_failed",
                    "本接口需要单张图片结果",
                    uncertain=True,
                    health_failure=False,
                )
            usage = sdk_images.raw_counts(attempt.transport.response_body or {})
            attempt.trace.observe_usage({"source": "upstream", **usage})
            image = await deliver_image(data[0], settings)
            usage = {
                **usage,
                "image_count": 1,
                "image_width": image.width,
                "image_height": image.height,
            }
            attempt.trace.observe_usage(usage, phase="confirmed_delivery")
            output = {
                "id": str(log.id),
                "created": int(time.time()),
                "data": [image.model_dump()],
                "usage": usage,
            }
        elif isinstance(body, SpeechInput):
            audio = deliver_audio(response.content)
            usage = {
                "input_characters": len(body.input),
                "billing_source": "platform_input_characters",
                "supplier_usage_source": "unknown",
                "audio_duration_ms": audio.duration_ms,
            }
            attempt.trace.observe_usage(
                {"input_characters": len(body.input)}, phase="validated_input"
            )
            output = {"id": str(log.id), "audio": audio.model_dump(), "usage": usage}
        else:
            raw = response.model_dump(exclude_none=True)
            text = raw.get("text")
            if not isinstance(text, str) or len(text) > 100000:
                raise retrieval.UpstreamFailure(
                    502,
                    "transcript_invalid",
                    "上游未返回有效转写结果",
                    uncertain=True,
                    health_failure=False,
                )
            segments = None
            if body.response_format == "verbose_json":
                try:
                    items = raw.get("segments")
                    if not isinstance(items, list) or len(items) > 2000:
                        raise ValueError("Missing segments")
                    segments = [TranscriptSegment.model_validate(item) for item in items]
                    if any(
                        s.end < s.start or s.end > body.duration_ms / 1000 + 1 for s in segments
                    ):
                        raise ValueError("Invalid timestamps")
                except ValueError:
                    raise retrieval.UpstreamFailure(
                        502,
                        "transcript_invalid",
                        "上游分段时间戳无效",
                        uncertain=True,
                        health_failure=False,
                    ) from None
            usage = {
                "audio_duration_ms": body.duration_ms,
                "billing_source": "platform_audio_duration",
                "supplier_usage_source": "unknown",
            }
            supplied = (attempt.transport.response_body or {}).get("usage")
            if isinstance(supplied, dict):
                original = {
                    k: v
                    for k, v in supplied.items()
                    if k in ("input_tokens", "output_tokens", "total_tokens", "seconds")
                    and type(v) is int
                    and 0 <= v <= 1000000000
                }
                if original:
                    usage.update(supplier_usage_source="upstream", supplier_usage=original)
            attempt.trace.observe_usage(
                {"audio_duration_ms": body.duration_ms}, phase="validated_input"
            )
            output = {
                "id": str(log.id),
                "text": text,
                "segments": [s.model_dump() for s in segments] if segments is not None else None,
                "usage": usage,
            }
        result_ready = True
        await watch.check()
        watch.enforce()
        attempt.trace.mark_output()
    except BaseException as exc:
        error = watch.error or exc
        if invocation.attempts:
            last = invocation.attempts[-1]
            if isinstance(exc, HTTPException) and not result_ready:
                last.error = exc
            last.trace.finish(
                error=None if result_ready else exc,
                cancelled=isinstance(exc, (asyncio.CancelledError, GeneratorExit)),
            )
            if not usage:
                usage = selected_usage(last.transport.meter)
    finally:
        with anyio.move_on_after(3, shield=True):
            if stream is not None and hasattr(stream, "aclose"):
                await stream.aclose()
            await watch.close()
            attempts = invocation.snapshots()
            if attempts:
                attempts[-1]["usage"] = usage
                if error is not None and not result_ready:
                    attempts[-1]["status"] = (
                        "unknown"
                        if isinstance(error, (asyncio.CancelledError, GeneratorExit))
                        else "failed"
                    )
                for item in attempts:
                    prices = item["prices"]
                    from app.modules.llm.catalog_schemas import TokenPrice

                    item["estimates"] = {
                        name: valuation(
                            TokenPrice.model_validate(price) if price else None, item["usage"]
                        )
                        for name, price in prices.items()
                    }
            record.update(
                complete=True,
                attempts=attempts,
                status="succeeded"
                if error is None
                else "unknown"
                if isinstance(error, (asyncio.CancelledError, GeneratorExit))
                else "failed",
                delivered=result_ready,
                no_send=not attempts and isinstance(error, HTTPException),
                error_code=getattr(
                    error,
                    "code",
                    "caller_cancelled"
                    if isinstance(error, (asyncio.CancelledError, GeneratorExit))
                    else "execution_error"
                    if error
                    else None,
                ),
                termination_code=getattr(
                    error,
                    "code",
                    "caller_cancelled"
                    if isinstance(error, (asyncio.CancelledError, GeneratorExit))
                    else "execution_error"
                    if error
                    else None,
                ),
                duration_ms=int((time.monotonic() - started) * 1000),
                usage=usage,
                estimates=attempts[-1]["estimates"] if attempts else {},
            )
            if config.gateway:
                record["gateway_billing_deadline"] = time.time() + 60
            await outbox.checkpoint(record)
            await outbox.flush(log.id)
            await invocation.close()
    if error is not None:
        raise error
    assert output is not None
    yield output
