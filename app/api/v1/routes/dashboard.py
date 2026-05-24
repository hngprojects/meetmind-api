import logging
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.responses import success
from app.db.session import get_session
from app.services.dashboard import (
    get_completed,
    get_live_counts,
    get_live_interviews,
    get_schedule,
)

router = APIRouter()
logger = logging.getLogger(__name__)


async def _resolve_workspace(user: CurrentUser, db: AsyncSession) -> uuid.UUID | None:
    """Resolve the workspace the current user belongs to, or None if not found."""
    from sqlalchemy import select

    from app.models.workspace import WorkspaceMember

    result = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
    )
    return result.scalar_one_or_none()


_EMPTY_STATS = {
    "total": 0,
    "in_progress": 0,
    "scheduled": 0,
    "completed": 0,
    "needs_attention": 0,
}


@router.get("/overview", status_code=status.HTTP_200_OK)
async def get_dashboard_overview(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Return high-level session counts and whether the user has any sessions.

    Powers the summary cards and empty-state detection on the dashboard.
    """
    workspace_id = await _resolve_workspace(user, db)
    if workspace_id is None:
        return success(
            {"has_sessions": False, "stats": _EMPTY_STATS},
            message="Dashboard overview retrieved successfully",
        )
    counts = await get_live_counts(workspace_id, db)
    return success(
        {"has_sessions": counts.total > 0, "stats": counts.model_dump()},
        message="Dashboard overview retrieved successfully",
    )


@router.get("/live", status_code=status.HTTP_200_OK)
async def get_dashboard_live(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Return a count breakdown of all interviews in the workspace by status,
    alongside a list of live and upcoming interviews for the sidebar.
    """
    workspace_id = await _resolve_workspace(user, db)
    if workspace_id is None:
        return success(
            {**_EMPTY_STATS, "live_interviews": []},
            message="Dashboard live counts retrieved successfully",
        )

    counts = await get_live_counts(workspace_id, db)
    interviews = await get_live_interviews(workspace_id, db)

    return success(
        {
            **counts.model_dump(),
            "live_interviews": [
                {
                    "id": str(item.interview_id),
                    "interview_id": str(item.interview_id),
                    "candidate_name": item.candidate_name,
                    "role_title": item.role_title,
                    "title": item.role_title,
                    "scheduled_at": None,
                    "status": "live"
                    if item.elapsed_seconds is not None
                    else "upcoming",
                }
                for item in interviews.live_interviews
            ],
        },
        message="Dashboard live counts retrieved successfully",
    )


@router.get("/live-sessions", status_code=status.HTTP_200_OK)
async def get_dashboard_live_sessions(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Return all currently in-progress interviews for the Live Now panel.

    Each item includes candidate name, role title, elapsed time in seconds,
    and question progress.
    """
    workspace_id = await _resolve_workspace(user, db)
    if workspace_id is None:
        return success([], message="Live sessions retrieved successfully")
    stats = await get_live_interviews(workspace_id, db)
    return success(
        stats.model_dump(mode="json")["live_interviews"],
        message="Live sessions retrieved successfully",
    )


@router.get("/schedule", status_code=status.HTTP_200_OK)
async def get_dashboard_schedule(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    """Return scheduled interviews within a date range.

    Powers the sidebar calendar agenda view.

    Query params:
        start_date: ISO date string e.g. 2026-05-29
        end_date:   ISO date string e.g. 2026-06-03
    """
    today = date.today()

    start_date = start_date or today
    end_date = end_date or (today + timedelta(days=30))
    workspace_id = await _resolve_workspace(user, db)
    if workspace_id is None:
        return success([], message="Schedule retrieved successfully")
    data = await get_schedule(workspace_id, db, start_date, end_date)
    return success(data, message="Schedule retrieved successfully")


@router.get("/completed", status_code=status.HTTP_200_OK)
async def get_dashboard_completed(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Return recently completed interview sessions with scores.

    Powers the completed sessions panel on the dashboard.
    """
    workspace_id = await _resolve_workspace(user, db)
    if workspace_id is None:
        return success([], message="Completed sessions retrieved successfully")
    data = await get_completed(workspace_id, db)
    return success(data, message="Completed sessions retrieved successfully")


@router.get("/alerts", status_code=status.HTTP_200_OK)
async def get_dashboard_alerts(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Return items requiring immediate attention.

    Stubbed for MVP — returns empty list. Will surface agent join failures,
    connectivity issues, and candidate no-shows in a later milestone.
    """
    return success([], message="Alerts retrieved successfully")
