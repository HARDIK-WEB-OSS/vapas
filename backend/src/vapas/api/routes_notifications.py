from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from vapas.auth.deps import CurrentUserDep
from vapas.db import cases as store

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    case_id: UUID | None
    kind: str
    message: str
    created_at: datetime
    read_at: datetime | None


@router.get("")
async def list_notifications(user: CurrentUserDep, unread_only: bool = False) -> list[NotificationOut]:
    return [NotificationOut(**n) for n in await store.notifications(user.conn, user.user_id, unread_only)]


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(notification_id: UUID, user: CurrentUserDep) -> None:
    if not await store.mark_read(user.conn, notification_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
