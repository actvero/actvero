"""Bounded multipart ingress; upload contents are transient and never logged."""

import base64
from contextlib import aclosing
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.modules.auth.router import Mutation
from app.modules.auth.service import DB
from app.modules.desktop.errors import fail
from app.modules.llm import runtime
from app.modules.llm.audio_delivery import MAX_AUDIO_BYTES, deliver_audio
from app.modules.llm.audio_schemas import TranscriptionInput, TranscriptionOutput
from app.modules.llm.body_limit import AudioUploadRoute
from app.modules.llm.inference_router import resource
from app.modules.llm.providers.retrieval import UpstreamFailure
from app.modules.llm.router import administrator

router = APIRouter(
    route_class=AudioUploadRoute,
    prefix=runtime.BASE,
    tags=["llm-gateway"],
    dependencies=[Depends(resource)],
)
admin_router = APIRouter(
    route_class=AudioUploadRoute, prefix="/api/v1/llm/models", tags=["llm-tests"]
)
UPLOAD = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["model", "file"],
                    "properties": {
                        "model": {"type": "string", "maxLength": 200},
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "PCM WAV，最多 8 MB / 120 秒",
                        },
                        "language": {"type": "string", "pattern": "^[a-z]{2}$"},
                        "response_format": {
                            "type": "string",
                            "enum": ["json", "verbose_json"],
                            "default": "json",
                        },
                    },
                }
            }
        },
    }
}


async def parse_upload(request: Request) -> TranscriptionInput:
    if not request.headers.get("content-type", "").startswith("multipart/form-data;"):
        fail(415, "multipart_required", "请上传 multipart/form-data 音频")
    async with request.form(max_files=1, max_fields=3, max_part_size=1024) as form:
        names = list(form.keys())
        if set(names) - {"file", "model", "language", "response_format"} or any(
            len(form.getlist(name)) != 1 for name in names
        ):
            fail(422, "invalid_audio_fields", "文件或参数重复，或包含不支持的字段")
        file = form.get("file")
        if not isinstance(file, UploadFile):
            fail(422, "audio_required", "请选择音频文件")
        content = await file.read(MAX_AUDIO_BYTES + 1)
        try:
            audio = deliver_audio(content)
        except UpstreamFailure:
            fail(422, "audio_invalid", "请上传完整的 PCM WAV，最多 8 MB / 120 秒")
        try:
            return TranscriptionInput.model_validate(
                {
                    "model": form.get("model"),
                    "language": form.get("language"),
                    "response_format": form.get("response_format", "json"),
                    "audio": base64.b64decode(audio.b64_json),
                    "duration_ms": audio.duration_ms,
                }
            )
        except ValidationError:
            fail(422, "transcription_input_invalid", "模型、语言或返回格式无效")


async def invoke(
    request: Request,
    db: DB,
    body: TranscriptionInput,
    model_id: UUID,
    *,
    test: bool = False,
    specific: tuple[UUID, str] | None = None,
) -> TranscriptionOutput:
    async with aclosing(
        runtime.execute(request, db, model_id, body, test=test, specific=specific)
    ) as events:
        return TranscriptionOutput.model_validate(await anext(events))


@router.post(
    "/audio/transcriptions",
    response_model=TranscriptionOutput,
    summary="上传音频并转写为文字",
    openapi_extra=UPLOAD,
)
async def transcribe(request: Request, db: DB) -> TranscriptionOutput:
    await runtime.authorize(request, db)
    body = await parse_upload(request)
    return await invoke(request, db, body, await runtime.resolve_model(request, db, body.model))


@admin_router.post(
    "/{model_id}/test/transcriptions",
    response_model=TranscriptionOutput,
    summary="管理员语音转文字测试，不占成员额度",
    openapi_extra=UPLOAD,
)
async def test_transcription(
    model_id: UUID,
    request: Request,
    db: DB,
    _: Mutation,
    channel_id: UUID | None = None,
    upstream_id: str = Query("", max_length=200),
) -> TranscriptionOutput:
    await administrator(request, db, write=True)
    if bool(channel_id) != bool(upstream_id):
        fail(422, "invalid_route", "指定测试须同时提供渠道和上游模型")
    return await invoke(
        request,
        db,
        await parse_upload(request),
        model_id,
        test=True,
        specific=(channel_id, upstream_id) if channel_id else None,
    )
