from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from vapas.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True, pool_size=5)


async def ping_database(engine: AsyncEngine) -> bool:
    async with engine.connect() as connection:
        return bool(await connection.scalar(text("select 1")) == 1)
