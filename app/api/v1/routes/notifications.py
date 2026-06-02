import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import APIResponse, success
from app.db.session import get_session
from app.schemas.notification import NotificationListData, NotificationResponse
from app.services.notification_service import NotificationService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("", response_model=APIResponse[NotificationListData])
async def list_notifications(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
    page: int = 1,
    page_size: int = 20,
    filter: str | None = None,
):
    notifs, total = await NotificationService.list_for_user(
        db=db,
        user_id=user.id,
        page=page,
        page_size=page_size,
        filter=filter,
    )

    unread_count = await NotificationService.count_unread(db=db, user_id=user.id)

    items = [
        NotificationResponse.model_validate(n).model_dump(mode="json") for n in notifs
    ]

    return success(
        {"notifications": items, "unread_count": unread_count},
        message="Notifications retrieved",
    )


@router.patch("/mark-all-read", response_model=APIResponse[None])
async def mark_all_read(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    await NotificationService.mark_all_read(db=db, user_id=user.id)
    return success(message="All notifications marked as read")


@router.patch(
    "/{notification_id}/read", response_model=APIResponse[NotificationResponse]
)
async def mark_read(
    notification_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    notif = await NotificationService.mark_read(
        db=db,
        notification_id=notification_id,
        user_id=user.id,
    )
    data = NotificationResponse.model_validate(notif).model_dump(mode="json")
    return success(data, message="Notification marked as read")


@router.delete("", response_model=APIResponse[None])
async def clear_notifications(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    await NotificationService.soft_delete_all(db=db, user_id=user.id)
    return success(message="Notifications cleared")
