import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.notification import Notification

logger = logging.getLogger(__name__)


def time_display(dt: datetime, now: datetime) -> str:
    delta = now - dt
    if delta < timedelta(seconds=60):
        return "Just now"
    if delta < timedelta(minutes=60):
        return f"{int(delta.total_seconds() // 60)} min ago"
    if delta < timedelta(hours=24):
        if dt.date() == (now - timedelta(days=1)).date():
            return "Yesterday"
        return f"{int(delta.total_seconds() // 3600)} hours ago"
    if dt.date() == (now - timedelta(days=1)).date():
        return "Yesterday"
    return dt.strftime("%a %b %d")


class NotificationService:

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id,
        type: str,
        title: str,
        description: Optional[str] = None,
        action_label: Optional[str] = None,
        action_url: Optional[str] = None,
    ) -> Notification:
        notif = Notification(
            user_id=user_id,
            type=type,
            title=title,
            description=description,
            action_label=action_label,
            action_url=action_url,
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)
        return notif

    @staticmethod
    async def list_for_user(
        db: AsyncSession,
        user_id,
        page: int = 1,
        page_size: int = 20,
        filter: Optional[str] = None,
    ) -> tuple[list[Notification], int]:
        query = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.deleted_at.is_(None))
            .order_by(Notification.created_at.desc())
        )

        count_query = (
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.deleted_at.is_(None))
        )

        if filter == "unread":
            query = query.where(Notification.is_read.is_(False))
            count_query = count_query.where(Notification.is_read.is_(False))

        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        result = await db.execute(query)
        notifs = list(result.scalars().all())

        count_result = await db.execute(count_query)
        total = count_result.scalar()

        return notifs, total

    @staticmethod
    async def mark_read(
        db: AsyncSession,
        notification_id,
        user_id,
    ) -> Notification:
        result = await db.execute(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        )
        notif = result.scalar_one_or_none()
        if not notif:
            raise APIError(
                message="Notification not found",
                status_code=404,
                code="notification_not_found",
            )
        notif.is_read = True
        await db.commit()
        await db.refresh(notif)
        return notif

    @staticmethod
    async def mark_all_read(db: AsyncSession, user_id) -> None:
        await db.execute(
            update(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.deleted_at.is_(None))
            .values(is_read=True)
        )
        await db.commit()

    @staticmethod
    async def soft_delete_all(db: AsyncSession, user_id) -> None:
        await db.execute(
            update(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.deleted_at.is_(None))
            .values(deleted_at=datetime.now(timezone.utc))
        )
        await db.commit()
 
    @staticmethod
    async def count_unread(db: AsyncSession, user_id) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
            .where(Notification.deleted_at.is_(None))
            .where(Notification.is_read.is_(False))
        )
        return result.scalar()