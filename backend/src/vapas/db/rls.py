from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def set_user_context(connection: AsyncConnection, user_id: UUID) -> None:
    await connection.execute(text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id)})
