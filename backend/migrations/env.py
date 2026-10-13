import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.core.models  # noqa: F401
from app.core.config import Settings
from app.core.database import Base

settings = Settings()
if settings.database_url is None:
    raise RuntimeError("ACTVERO_DATABASE_URL is required for migrations")
url = settings.database_url.get_secret_value()
target_metadata = Base.metadata


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.config.attributes.get("connection") is not None:
    run_migrations(context.config.attributes["connection"])
elif context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
