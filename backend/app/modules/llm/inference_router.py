import base64
from contextlib import aclosing
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from fastapi.security import HTTPBearer
from sqlalchemy import select

from app.modules.access_keys import service as keys
from app.modules.auth.router import Mutation
from app.modules.auth.service import DB, now
from app.modules.desktop.errors import fail
from app.modules.desktop.schemas import DesktopErrorResponse
from app.modules.llm import member_catalog, routing, runtime
from app.modules.llm.audio_schemas import SpeechInput, SpeechOutput
from app.modules.llm.body_limit import InferenceRoute
from app.modules.llm.catalog_schemas import CatalogInput
from app.modules.llm.image_schemas import ImageInput, ImageOutput
from app.modules.llm.inference_schemas import (
    CallView,
    EmbeddingInput,
    EmbeddingOutput,
    InferenceConflictResponse,
    PublicModels,
    RerankInput,
    RerankOutput,
    RouteStateView,
)
from app.modules.llm.models import ModelCall
from app.modules.llm.router import administrator

resource = HTTPBearer(
    scheme_name="LlmResource",
    auto_error=False,
    description=(
        "接受含对应模型权限的个人访问密钥，或通过 desktop/resource-tokens "
        "申请的 llm:catalog / llm:<模型UUID> 资源令牌。"
    ),
)
router = APIRouter(
    route_class=InferenceRoute,
    prefix=runtime.BASE,
    tags=["llm-gateway"],
    dependencies=[Depends(resource)],
    responses={
        status: {
            "model": InferenceConflictResponse if status == 409 else DesktopErrorResponse,
            "description": description,
        }
        for status, description in {
            401: "访问密钥不可用、资源令牌过期或设备登录失效。",
            403: "资源范围不符或成员访问被拒绝。",
            404: "模型未开放、已归档或未获授权。",
            409: "配置未就绪/已变化；幂等重复或内容冲突返回本人call_id与状态，不重放正文。",
            413: "请求体超过 2 MB。",
            415: "不接受压缩请求体。",
            422: "输入、模型用途或维度不符合契约。",
            429: "成员积分额度不足，或上游限流且已按路由策略处理。",
            502: "上游连接失败、拒绝请求或结果不符合契约。",
            504: "上游超时；不代表未产生费用。",
        }.items()
    },
)
admin_router = APIRouter(
    route_class=InferenceRoute, prefix="/api/v1/llm/models", tags=["llm-tests"]
)


@router.get("/models", response_model=PublicModels, summary="读取已授权模型与积分单价")
async def models(request: Request, db: DB, page: int = Query(1, ge=1)) -> PublicModels:
    actor = await runtime.authorize(request, db, "llm:catalog")
    result = await member_catalog.public_page(db, actor, page, request)
    if isinstance(actor, keys.KeyActor):
        actor.key.last_used_at = now()
        await db.commit()
    return result


async def invoke(
    request: Request, db: DB, body: EmbeddingInput | RerankInput
) -> EmbeddingOutput | RerankOutput:
    model_id = await runtime.resolve_model(request, db, body.model)
    return await runtime.invoke(request, db, model_id, body)


@router.post(
    "/embeddings", response_model=EmbeddingOutput, summary="调用向量模型（文本、浮点向量）"
)
async def embeddings(
    request: Request, db: DB, body: EmbeddingInput
) -> EmbeddingOutput | RerankOutput:
    return await invoke(request, db, body)


@router.post("/rerank", response_model=RerankOutput, summary="调用重排模型（Cohere 风格）")
async def rerank(request: Request, db: DB, body: RerankInput) -> EmbeddingOutput | RerankOutput:
    return await invoke(request, db, body)


async def image_response(
    request: Request,
    db: DB,
    model_id: UUID,
    body: ImageInput,
    *,
    test: bool = False,
    specific: tuple[UUID, str] | None = None,
) -> ImageOutput:
    async with aclosing(
        runtime.execute(request, db, model_id, body, test=test, specific=specific)
    ) as events:
        return ImageOutput.model_validate(await anext(events))


@router.post(
    "/images/generations", response_model=ImageOutput, summary="生成单张图片，返回受控 Base64 结果"
)
async def images(request: Request, db: DB, body: ImageInput) -> ImageOutput:
    model_id = await runtime.resolve_model(request, db, body.model)
    return await image_response(request, db, model_id, body)


@admin_router.post(
    "/{model_id}/test/images", response_model=ImageOutput, summary="管理员图片测试，不占成员额度"
)
async def test_images(
    model_id: UUID,
    request: Request,
    db: DB,
    body: ImageInput,
    _: Mutation,
    channel_id: UUID | None = None,
    upstream_id: str = Query("", max_length=200),
) -> ImageOutput:
    if bool(channel_id) != bool(upstream_id):
        fail(422, "invalid_route", "指定测试须同时提供渠道和上游模型")
    return await image_response(
        request,
        db,
        model_id,
        body,
        test=True,
        specific=(channel_id, upstream_id) if channel_id else None,
    )


async def speech_response(
    request: Request,
    db: DB,
    model_id: UUID,
    body: SpeechInput,
    *,
    test: bool = False,
    specific: tuple[UUID, str] | None = None,
) -> SpeechOutput:
    async with aclosing(
        runtime.execute(request, db, model_id, body, test=test, specific=specific)
    ) as events:
        return SpeechOutput.model_validate(await anext(events))


@router.post(
    "/audio/speech",
    response_class=Response,
    responses={200: {"content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}}}},
    summary="合成语音，返回 WAV 音频",
)
async def speech(request: Request, db: DB, body: SpeechInput) -> Response:
    model_id = await runtime.resolve_model(request, db, body.model)
    result = await speech_response(request, db, model_id, body)
    return Response(
        base64.b64decode(result.audio.b64_json),
        media_type="audio/wav",
        headers={
            "Content-Disposition": 'inline; filename="actvero-speech.wav"',
            "X-Actvero-Call-Id": result.id,
            "Cache-Control": "no-store",
        },
    )


@admin_router.post(
    "/{model_id}/test/speech",
    response_model=SpeechOutput,
    summary="管理员语音合成测试，不占成员额度",
)
async def test_speech(
    model_id: UUID,
    request: Request,
    db: DB,
    body: SpeechInput,
    _: Mutation,
    channel_id: UUID | None = None,
    upstream_id: str = Query("", max_length=200),
) -> SpeechOutput:
    if bool(channel_id) != bool(upstream_id):
        fail(422, "invalid_route", "指定测试须同时提供渠道和上游模型")
    return await speech_response(
        request,
        db,
        model_id,
        body,
        test=True,
        specific=(channel_id, upstream_id) if channel_id else None,
    )


@admin_router.post(
    "/{model_id}/test/embeddings",
    response_model=EmbeddingOutput,
    summary="管理员真实向量测试，会调用上游并产生上游费用",
)
async def test_embeddings(
    model_id: UUID,
    request: Request,
    db: DB,
    body: EmbeddingInput,
    _csrf: Mutation,
    channel_id: UUID | None = None,
    upstream_id: str = Query("", max_length=200),
) -> EmbeddingOutput | RerankOutput:
    if bool(channel_id) != bool(upstream_id):
        fail(422, "invalid_route", "指定渠道测试须同时提供渠道和上游模型")
    return await runtime.invoke(
        request,
        db,
        model_id,
        body,
        test=True,
        specific=(channel_id, upstream_id) if channel_id else None,
    )


@admin_router.post(
    "/{model_id}/test/rerank",
    response_model=RerankOutput,
    summary="管理员真实重排测试，会调用上游并产生上游费用",
)
async def test_rerank(
    model_id: UUID,
    request: Request,
    db: DB,
    body: RerankInput,
    _csrf: Mutation,
    channel_id: UUID | None = None,
    upstream_id: str = Query("", max_length=200),
) -> EmbeddingOutput | RerankOutput:
    if bool(channel_id) != bool(upstream_id):
        fail(422, "invalid_route", "指定渠道测试须同时提供渠道和上游模型")
    return await runtime.invoke(
        request,
        db,
        model_id,
        body,
        test=True,
        specific=(channel_id, upstream_id) if channel_id else None,
    )


@admin_router.get(
    "/{model_id}/calls", response_model=list[CallView], summary="管理员调用记录（无请求正文）"
)
async def calls(model_id: UUID, request: Request, db: DB) -> list[CallView]:
    actor = await administrator(request, db)
    from app.modules.llm.catalog_router import get_model

    await get_model(db, actor, model_id)
    rows = await db.scalars(
        select(ModelCall)
        .where(ModelCall.model_id == model_id, ModelCall.tenant_id == actor.tenant.id)
        .order_by(ModelCall.created_at.desc())
        .limit(20)
    )
    return [CallView.model_validate(row, from_attributes=True) for row in rows]


@admin_router.get(
    "/{model_id}/routes",
    response_model=list[RouteStateView],
    summary="管理员路由健康与契约测试状态",
)
async def routes(model_id: UUID, request: Request, db: DB) -> list[RouteStateView]:
    actor = await administrator(request, db)
    row = await runtime.model_for_actor(db, actor, model_id)
    catalog = CatalogInput.model_validate(row.configuration)
    result = []
    for config in catalog.execution_configs():
        channels = await routing.channels_for(db, actor.tenant.id, config)
        for binding in config.bindings:
            state, health = await routing.state(
                db,
                actor.tenant.id,
                model_id,
                config,
                binding,
                channels.get(binding.channel_id),
                require_test=True,
            )
            result.append(
                RouteStateView(
                    operation=config.kind,
                    channel_id=binding.channel_id,
                    upstream_id=binding.upstream_id,
                    state=state,
                    tested_at=health.tested_at if health else None,
                    cooldown_until=health.cooldown_until if health else None,
                    failures=health.failures if health else 0,
                )
            )
    return result
