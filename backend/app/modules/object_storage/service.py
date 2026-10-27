from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import provider
from app.modules.object_storage.models import ObjectStorage as ClientStorage
from app.modules.object_storage.storage import ObjectStore


async def storage(db: AsyncSession, ident: UUID | None) -> ClientStorage:
    row = (
        await db.get(ClientStorage, ident)
        if ident
        else await db.scalar(
            select(ClientStorage).where(
                ClientStorage.is_default.is_(True), ClientStorage.enabled.is_(True)
            )
        )
    )
    if not row or not row.enabled:
        raise HTTPException(422, "请在设置中配置并启用默认对象存储")
    return row


def store(request: Request, row: ClientStorage) -> ObjectStore:
    factory = getattr(request.app.state, "client_store_factory", ObjectStore)
    return factory(row, provider(request).unseal(row.credentials))


async def download_url(request: Request, row: ClientStorage, key: str) -> str:
    return f"{row.public_url}/{key}" if row.public_url else await store(request, row).sign_get(key)
