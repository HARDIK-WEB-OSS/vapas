from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from vapas.config import Settings
from vapas.db.rls import set_user_context


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True, pool_size=5)


async def ping_database(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        return bool(await connection.scalar(text("select 1")) == 1)


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @asynccontextmanager
    async def anonymous(self) -> AsyncIterator[AsyncConnection]:
        async with self.engine.begin() as connection:
            yield connection

    @asynccontextmanager
    async def as_user(self, user_id: UUID) -> AsyncIterator[AsyncConnection]:
        async with self.engine.begin() as connection:
            await set_user_context(connection, user_id)
            yield connection
