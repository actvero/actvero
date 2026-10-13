"""Task adapters for OpenAI embeddings and Cohere-style rerank-compatible endpoints."""

import math
from typing import TYPE_CHECKING, Any, Literal

from app.core.config import Settings
from app.modules.desktop.errors import DesktopError, fail
from app.modules.llm.catalog_schemas import RetrievalOptions
from app.modules.llm.inference_schemas import (
    EmbeddingInput,
    EmbeddingItem,
    EmbeddingOutput,
    EmbeddingUsage,
    RerankInput,
    RerankItem,
    RerankOutput,
)
from app.modules.llm.providers.connection import OperationTarget

if TYPE_CHECKING:
    from app.modules.llm.providers.attempt import AttemptTrace


class UpstreamFailure(DesktopError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        upstream_status: int | None = None,
        retryable: bool = False,
        uncertain: bool = False,
        auth_failure: bool = False,
        health_failure: bool = True,
        retry_after: int | None = None,
        binding_failure: bool = False,
        binding_failure_reason: Literal["model_unavailable", "unclassified_rejection"]
        | None = None,
    ):
        super().__init__(status, code, message)
        self.upstream_status = upstream_status
        self.retryable = retryable
        self.uncertain = uncertain
        self.auth_failure = auth_failure
        self.health_failure = health_failure
        self.retry_after = retry_after
        self.binding_failure = binding_failure
        self.binding_failure_reason = binding_failure_reason


async def post(
    base: str,
    path: str,
    key: str | None,
    timeout: float,
    settings: Settings,
    payload: dict[str, Any],
    *,
    target: OperationTarget | None = None,
    trace: "AttemptTrace | None" = None,
) -> dict[str, Any]:
    # Lazy import keeps shared failure/result contracts independent of SDK loading.
    from app.modules.llm.providers import sdk_retrieval

    return await sdk_retrieval.post(
        base, path, key, timeout, settings, payload, target=target, trace=trace
    )


def count(value: Any) -> int | None:
    # Only explicit, bounded, integer meters; missing usage is never fabricated as zero.
    return value if type(value) is int and 0 <= value <= 10**12 else None


def prepare(
    body: EmbeddingInput | RerankInput, limits: RetrievalOptions, upstream_id: str
) -> tuple[str, dict[str, Any], int]:
    texts = (
        ([body.input] if isinstance(body.input, str) else body.input)
        if isinstance(body, EmbeddingInput)
        else body.documents
    )
    if len(texts) > limits.max_batch_size or any(
        not text.strip() or len(text) > limits.max_input_characters for text in texts
    ):
        fail(422, "input_limit_exceeded", "输入数量或单条长度超过模型限制")
    if isinstance(body, RerankInput) and (
        not body.query.strip() or len(body.query) > limits.max_input_characters
    ):
        fail(422, "input_limit_exceeded", "查询长度超过模型限制")
    if (
        isinstance(body, EmbeddingInput)
        and body.dimensions is not None
        and (body.dimensions not in limits.dimension_options)
    ):
        fail(422, "unsupported_dimensions", "该模型未声明支持此维度参数")
    payload = body.model_dump(exclude_none=True)
    payload["model"] = upstream_id
    if isinstance(body, EmbeddingInput) and body.dimensions is None and limits.dimension_options:
        payload["dimensions"] = limits.dimensions
    path = "/embeddings" if isinstance(body, EmbeddingInput) else "/rerank"
    chars = sum(len(text) for text in texts)
    if isinstance(body, RerankInput):
        chars += len(body.query)
    return path, payload, chars


def normalize(
    raw: dict[str, Any],
    body: EmbeddingInput | RerankInput,
    limits: RetrievalOptions,
    request_id: str,
) -> tuple[EmbeddingOutput | RerankOutput, dict[str, Any]]:
    try:
        if isinstance(body, EmbeddingInput):
            data = raw["data"]
            size = 1 if isinstance(body.input, str) else len(body.input)
            if not isinstance(data, list) or len(data) != size:
                raise ValueError("count")
            items = []
            dims = body.dimensions or limits.dimensions
            seen = set()
            for entry in data:
                index, vector = entry["index"], entry["embedding"]
                if type(index) is not int or not 0 <= index < size or index in seen:
                    raise ValueError("index")
                if not isinstance(vector, list) or not vector or len(vector) > 65536:
                    raise ValueError("vector")
                if dims is None:
                    dims = len(vector)
                if len(vector) != dims or any(
                    type(v) not in (int, float) or not math.isfinite(v) for v in vector
                ):
                    raise ValueError("dimensions or finite values")
                seen.add(index)
                items.append(EmbeddingItem(index=index, embedding=vector))
            reported = raw.get("usage")
            reported = reported if isinstance(reported, dict) else {}
            tokens = count(reported.get("prompt_tokens"))
            usage = {
                "input_tokens": tokens,
                "source": "upstream" if tokens is not None else "unknown",
            }
            return EmbeddingOutput(
                model=body.model,
                data=sorted(items, key=lambda e: e.index),
                usage=EmbeddingUsage(prompt_tokens=tokens, total_tokens=tokens),
            ), usage
        results = raw["results"]
        expected = body.top_n or len(body.documents)
        if not isinstance(results, list) or len(results) != expected:
            raise ValueError("results")
        ranked = []
        seen = set()
        for entry in results:
            index, score = entry["index"], entry["relevance_score"]
            if (
                type(index) is not int
                or not 0 <= index < len(body.documents)
                or index in seen
                or type(score) not in (int, float)
                or not math.isfinite(score)
            ):
                raise ValueError("rank")
            seen.add(index)
            ranked.append(RerankItem(index=index, relevance_score=score))
        meta = raw.get("meta")
        billed = meta.get("billed_units") if isinstance(meta, dict) else None
        billed = billed if isinstance(billed, dict) else {}
        reported = raw.get("usage")
        reported = reported if isinstance(reported, dict) else {}
        tokens = count(billed.get("input_tokens"))
        if tokens is None:
            tokens = count(reported.get("total_tokens"))
        searches = count(billed.get("search_units"))
        usage = {
            "input_tokens": tokens,
            "search_units": searches,
            "source": "upstream" if tokens is not None or searches is not None else "unknown",
        }
        clean = {
            k: v
            for k, v in {"input_tokens": tokens, "search_units": searches}.items()
            if v is not None
        }
        return RerankOutput(
            id=request_id,
            results=sorted(ranked, key=lambda e: -e.relevance_score),
            meta={"billed_units": clean},
        ), usage
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise UpstreamFailure(
            502,
            "invalid_upstream_response",
            "结果数量、索引或维度不符合本接口契约",
            uncertain=True,
            health_failure=False,
        ) from None
