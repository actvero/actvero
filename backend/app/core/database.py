from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    """Base for business models; tenant-owned tables must include tenant scope."""


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine: AsyncEngine | None = (
            create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
            if settings.database_url
            else None
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> bool:
        if self.engine is None:
            return False
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
