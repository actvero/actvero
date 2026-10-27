"""Read-only native admission estimate; Actvero never implements supplier pricing."""

import time
from decimal import Decimal, localcontext
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request

from app.modules.desktop.errors import fail
from app.modules.llm.audio_schemas import SpeechInput, TranscriptionInput
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.chat_schemas import ChatInput
from app.modules.llm.image_schemas import ImageInput
from app.modules.llm.inference_schemas import EmbeddingInput, RerankInput
from app.modules.model_gateway import client


async def estimate(
    request: Request,
    tenant: UUID,
    config: CatalogInput,
    body: ChatInput | EmbeddingInput | RerankInput | ImageInput | SpeechInput | TranscriptionInput,
) -> dict[str, Any]:
    connection = await client.relay_connection(request, tenant)
    if isinstance(body, ChatInput):
        input_limit = body._input_reservation or config.context_window
        output_limit = (
            body.max_completion_tokens
            or body.max_tokens
            or config.chat_policy.default_max_output
            or config.max_output
        )
    elif isinstance(body, (EmbeddingInput, RerankInput)):
        texts = (
            ([body.input] if isinstance(body.input, str) else body.input)
            if isinstance(body, EmbeddingInput)
            else [body.query, *body.documents]
        )
        input_limit, output_limit = sum(len(t.encode()) + 16 for t in texts), 1
    elif isinstance(body, ImageInput):
        input_limit, output_limit = 1, 1
    elif isinstance(body, SpeechInput):
        input_limit, output_limit = len(body.input), 1
    else:
        # Duration pricing requires a native task quantity bound, not fabricated tokens.
        fail(409, "quota_estimate_unavailable", "此用途尚无可验证的网关预留计算，请联系管理员")
    if not input_limit or not output_limit or not connection.relay_token_id:
        fail(409, "quota_estimate_unavailable", "模型缺少可计算预留额度的调用限制")
    chat_payload = None
    if isinstance(body, ChatInput):
        from app.modules.llm.providers.chat import prepare

        chat_payload = prepare(body, config, None)
    try:
        data = await client.call(
            request,
            tenant,
            "POST",
            "/api/option/model_pricing/preflight",
            payload={
                "model": config.slug,
                "token_id": connection.relay_token_id,
                "input_limit": input_limit,
                "output_limit": output_limit,
                **({"chat": chat_payload} if chat_payload is not None else {}),
            },
        )
    except HTTPException as exc:
        fail(
            409,
            "quota_estimate_unavailable",
            "无法取得网关计费预留，请检查网关版本、模型价格和调用分组",
        )
        raise AssertionError from exc
    try:
        valid = (
            data["schema_version"] == 1
            and data["model"] == config.slug
            and data["group"] == connection.relay_group
            and data["input_limit"] == input_limit
            and data["output_limit"] == output_limit
            and type(data["expires_at"]) is int
            and time.time() < data["expires_at"] <= time.time() + 90
            and isinstance(data["quota"], str)
            and data["quota"].isdigit()
            and isinstance(data["quota_per_unit"], str)
            and data["quota_per_unit"].isdigit()
            and 0 <= int(data["quota"]) <= 2**31 - 1
            and int(data["quota_per_unit"]) > 0
            and isinstance(data["pricing_version"], str)
            and isinstance(data["expression_hash"], str)
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        fail(502, "invalid_quota_estimate", "网关预留数据无法验证，未发起调用")
    with localcontext() as ctx:
        ctx.prec = 80
        amount = Decimal(data["quota"]) / Decimal(data["quota_per_unit"])
    return {"engine": "newapi", "currency": "USD", "reservation": data, "amount": str(amount)}
