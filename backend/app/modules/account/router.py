from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.modules.account.schemas import ProfileUpdate
from app.modules.account.service import MAX_AVATAR_BYTES, normalize_avatar, own_access
from app.modules.auth.router import Mutation
from app.modules.auth.schemas import UserView
from app.modules.auth.service import DB, limit
from app.modules.members.service import record
from app.modules.users.models import User

router = APIRouter(prefix="/api/v1/account", tags=["account"])


@router.patch("/profile", response_model=UserView)
async def update_profile(payload: ProfileUpdate, request: Request, db: DB, _: Mutation) -> UserView:
    actor = await own_access(request, db, write=True)
    if actor.user.name != payload.name:
        before = actor.user.name
        actor.user.name = payload.name
        actor.user.name_managed_locally = True
        record(
            db,
            actor,
            "account.profile",
            actor.user.id,
            payload.name,
            {"before_name": before, "after_name": payload.name},
        )
    await db.commit()
    return UserView.model_validate(actor.user)


@router.put(
    "/avatar",
    response_model=UserView,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                kind: {"schema": {"type": "string", "format": "binary"}}
                for kind in ("image/png", "image/jpeg", "image/webp")
            },
        }
    },
)
async def upload_avatar(request: Request, db: DB, _: Mutation) -> UserView:
    actor = await own_access(request, db)
    await limit(db, "avatar:" + str(actor.user.id), 20, 300)
    if request.headers.get("content-type", "").split(";")[0] not in {
        "image/png",
        "image/jpeg",
        "image/webp",
    }:
        raise HTTPException(415, "请选择 PNG、JPG 或 WebP 图片")
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_AVATAR_BYTES:
            raise HTTPException(413, "头像文件不能超过 2 MB")
        data.extend(chunk)
    normalized = await run_in_threadpool(normalize_avatar, bytes(data))
    # Recheck membership under the same tenant lock used by member revocation.
    actor = await own_access(request, db, write=True)
    actor.user.avatar_data = normalized
    actor.user.avatar_version = uuid4()
    record(db, actor, "account.avatar", actor.user.id, actor.user.name)
    await db.commit()
    return UserView.model_validate(actor.user)


@router.get(
    "/avatar",
    response_class=Response,
    responses={
        200: {"content": {"image/webp": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
async def avatar(request: Request, db: DB) -> Response:
    actor = await own_access(request, db)
    data = await db.scalar(select(User.avatar_data).where(User.id == actor.user.id))
    if data is None:
        raise HTTPException(404, "尚未设置头像")
    return Response(data, media_type="image/webp")


@router.delete("/avatar", response_model=UserView)
async def remove_avatar(request: Request, db: DB, _: Mutation) -> UserView:
    actor = await own_access(request, db, write=True)
    if actor.user.avatar_version:
        actor.user.avatar_data = None
        actor.user.avatar_version = None
        record(db, actor, "account.avatar_removed", actor.user.id, actor.user.name)
    await db.commit()
    return UserView.model_validate(actor.user)
