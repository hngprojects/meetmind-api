"""Shared utility functions used across the application."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import WorkspaceMember

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_async(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    task_name: str = "Task",
    **kwargs: Any,
) -> T:
    """Run an async function with retries and exponential backoff.

    Logs a warning on intermediate retries and an error on final exhaustion.
    """
    delay = initial_delay
    last_exception = None
    for attempt in range(1, max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except exceptions as e:
            last_exception = e
            logger.warning(
                "Attempt %d/%d failed for %s. Error: %s. Retrying in %.2fs...",
                attempt,
                max_retries,
                task_name,
                str(e),
                delay,
                exc_info=True,
            )
            if attempt == max_retries:
                break
            await asyncio.sleep(delay)
            delay *= backoff_factor

    logger.error(
        "All %d attempts failed for %s. Final exception: %s",
        max_retries,
        task_name,
        str(last_exception),
        exc_info=True,
    )
    raise last_exception



def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def format_time_display(start: datetime, end: datetime) -> str:
    """Computes 'Today 10:00AM - 10:30AM' or 'Mon Jun 13 10:00AM...'"""
    # Ensure datetimes are timezone aware (UTC)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)

    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()
    start_date = start.date()

    # Format time (e.g., 10:00AM)
    time_str = (
        f"{start.strftime('%I:%M%p').lstrip('0')} - "
        f"{end.strftime('%I:%M%p').lstrip('0')}"
    )

    if start_date == today:
        day_str = "Today"
    elif start_date == today + timedelta(days=1):
        day_str = "Tomorrow"
    else:
        day_str = start.strftime("%a %b %d")

    return f"{day_str} {time_str}"


def compute_available_slots(
    booked_intervals: list[tuple[datetime, datetime]], target_date: date
) -> list[dict]:
    """Pure function to compute available 30-min slots from 08:00 to 18:00 UTC."""
    if target_date < datetime.now(timezone.utc).date():
        return []

    slots = []
    start_of_day = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=timezone.utc
    ) + timedelta(hours=8)

    for i in range(20):
        slot_start = start_of_day + timedelta(minutes=30 * i)
        slot_end = slot_start + timedelta(minutes=30)

        is_blocked = any(
            b_start < slot_end and b_end > slot_start
            for b_start, b_end in booked_intervals
        )

        if not is_blocked:
            slots.append(
                {
                    "start_time": slot_start.strftime("%I:%M").lstrip("0"),
                    "end_time": slot_end.strftime("%I:%M").lstrip("0"),
                    "period_start": slot_start.strftime("%p"),
                    "period_end": slot_end.strftime("%p"),
                }
            )
    return slots


INTERVIEW_STATUS_MAP = {
    "in_progress": "ongoing",
    "completed": "completed",
    "needs_attention": "needs_review",
}


async def get_user_workspace(db: AsyncSession, user_id) -> uuid.UUID | None:
    result = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def safe_notify(
    db: AsyncSession,
    *,
    user_id,
    type: str,
    title: str,
    description: str | None = None,
    action_url: str | None = None,
    label: str = "notification",
) -> None:
    from app.services.notification_service import NotificationService

    try:
        await NotificationService.create(
            db=db,
            user_id=user_id,
            type=type,
            title=title,
            description=description,
            action_url=action_url,
        )
    except Exception:
        logger.exception("Failed to create %s", label)
