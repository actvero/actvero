"""Installation-wide object storage settings, independent of client release management."""

import io
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, update

from app.core.outbound import resolve
from app.modules.auth.schemas import Message
from app.modules.auth.service import DB, provider
from app.modules.object_storage.models import ObjectStorage as ClientStorage
from app.modules.object_storage.network import check_range
from app.modules.object_storage.schemas import StorageSave, StorageView
from app.modules.object_storage.service import download_url, storage, store
from app.modules.platform.operations import access, locked, revision

router = APIRouter(tags=["object-storage"])


@router.get("", response_model=dict[str, list[StorageView]])
async def list_storage(request: Request, db: DB) -> dict[str, list[StorageView]]:
    await access(request, db)
    return {
        "items": [
            StorageView.model_validate(s)
            for s in (await db.scalars(select(ClientStorage).order_by(ClientStorage.name))).all()
        ]
    }


@router.put("/{ident}", response_model=StorageView)
async def save_storage(ident: UUID, payload: StorageSave, request: Request, db: DB) -> StorageView:
    await access(request, db, "storage.manage")
    settings = provider(request).settings
    # Credentials are only sent to endpoints explicitly chosen by a platform operator.
    await db.rollback()
    await resolve(payload.endpoint, settings.client_distribution_allowed_private_origins)
    if payload.public_url:
        await resolve(payload.public_url, settings.client_distribution_allowed_private_origins)
    await locked(request, db, "storage.manage")
    row = await db.get(ClientStorage, ident)
    revision(row.revision if row else 0, payload.expected_revision)
    if await db.scalar(
        select(ClientStorage.id).where(
            ClientStorage.name == payload.name, ClientStorage.id != ident
        )
    ):
        raise HTTPException(409, "存储名称已存在")
    values = payload.model_dump(exclude={"expected_revision", "access_key", "secret_key"})
    if row:
        if row.locator_frozen:
            locator = {"endpoint", "bucket", "region", "prefix", "public_url", "path_style"}
            if any(getattr(row, k) != values[k] for k in locator):
                raise HTTPException(409, "此存储已有文件，地址不可原地修改；请新增存储配置")
        for key, value in values.items():
            setattr(row, key, value)
        row.revision += 1
    else:
        if not payload.access_key or not payload.secret_key:
            raise HTTPException(422, "新存储需要访问密钥和秘密密钥")
        row = ClientStorage(id=ident, **values)
        db.add(row)
    if payload.access_key and payload.secret_key:
        row.credentials = provider(request).seal(
            {
                "access_key": payload.access_key.get_secret_value(),
                "secret_key": payload.secret_key.get_secret_value(),
            }
        )
    if payload.is_default:
        await db.execute(
            update(ClientStorage)
            .where(ClientStorage.id != ident, ClientStorage.is_default.is_(True))
            .values(is_default=False, revision=ClientStorage.revision + 1)
        )
    await db.commit()
    return StorageView.model_validate(row)


@router.post("/{ident}/test", response_model=Message)
async def test_storage(ident: UUID, request: Request, db: DB) -> Message:
    await access(request, db, "storage.manage")
    profile = await storage(db, ident)
    client = store(request, profile)
    key = f"{profile.prefix}/checks/{uuid4().hex}"
    await db.commit()
    uploaded = False
    try:
        await client.put(key, io.BytesIO(b"actvero-storage-check"), 21)
        uploaded = True
        head = await client.head(key)
        url = await download_url(request, profile, key)
        if (
            not head
            or head.get("ContentLength") != 21
            or not await check_range(url, provider(request).settings, 21)
        ):
            raise HTTPException(422, "写入成功，但读取或 Range 校验未通过，请检查存储权限和连接")
    finally:
        if uploaded:
            await client.call("delete_object", Key=key)
    return Message(message="已验证写入、读取、单段 Range 和删除")
