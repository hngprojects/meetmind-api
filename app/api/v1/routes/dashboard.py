import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import APIResponse, success
from app.core.utils import get_user_workspace
from app.db.session import get_session
from app.schemas.dashboard import (
    CompletedInterviewItem,
    DashboardLiveInterviewItem,
    DashboardOverviewResponse,
    ScheduledInterviewItem,
)
from app.services.dashboard import (
    get_completed,
    get_live_counts,
    get_live_interviews,
    get_schedule,
)

router = APIRouter()
logger = logging.getLogger(__name__)


_EMPTY_STATS = {
    "total": 0,
    "in_progress": 0,
    "scheduled": 0,
    "completed": 0,
    "needs_attention": 0,
}


@router.get(
    "/overview",
    response_model=APIResponse[DashboardOverviewResponse],
    status_code=status.HTTP_200_OK,
)
async def get_dashboard_overview(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    """Return high-level session counts and whether the user has any sessions.

    Powers the summary cards and empty-state detection on the dashboard.
    """
    workspace_id = await get_user_workspace(db, user.id)
    if workspace_id is None:
        return success(
            {"has_sessions": False, "stats": _EMPTY_STATS},
            message="Dashboard overview retrieved successfully",
        )
    counts = await get_live_counts(workspace_id, db)
    return success(
        DashboardOverviewResponse(
            has_sessions=counts.total > 0,
            stats=counts,
        ),
        message="Dashboard overview retrieved successfully",
    )


@router.get(
    "/live",
    response_model=APIResponse[dict],  # mixed shape: counts + live_interviews list
    status_code=status.HTTP_200_OK,
)
async def get_dashboard_live(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    """Return a count breakdown of all interviews in the workspace by status,
    alongside a list of live and upcoming interviews for the sidebar.
    """
    workspace_id = await get_user_workspace(db, user.id)
    if workspace_id is None:
        return success(
            {**_EMPTY_STATS, "live_interviews": []},
            message="Dashboard live counts retrieved successfully",
        )

    counts = await get_live_counts(workspace_id, db)
    interviews = await get_live_interviews(workspace_id, db)
    live_items = [
        DashboardLiveInterviewItem(
            id=str(item.interview_id),
            interview_id=str(item.interview_id),
            candidate_name=item.candidate_name,
            role_title=item.role_title,
            title=item.role_title,
            scheduled_at=None,
            status="live" if item.elapsed_seconds is not None else "upcoming",
        )
        for item in interviews.live_interviews
    ]
    return success(
        {**counts.model_dump(), "live_interviews": live_items},
        message="Dashboard live counts retrieved successfully",
    )


@router.get(
    "/schedule",
    response_model=APIResponse[list[ScheduledInterviewItem]],
    status_code=status.HTTP_200_OK,
)
async def get_dashboard_live_sessions(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    """Return all currently in-progress interviews for the Live Now panel.

    Each item includes candidate name, role title, elapsed time in seconds,
    and question progress.
    """
    workspace_id = await get_user_workspace(db, user.id)
    if workspace_id is None:
        return success([], message="Live sessions retrieved successfully")
    stats = await get_live_interviews(workspace_id, db)
    return success(
        stats.live_interviews,
        message="Live sessions retrieved successfully",
    )


@router.get(
    "/schedule",
    response_model=APIResponse[list[ScheduledInterviewItem]],
    status_code=status.HTTP_200_OK,
)
async def get_dashboard_schedule(
    user: VerifiedUser,
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
    workspace_id = await get_user_workspace(db, user.id)
    if workspace_id is None:
        return success([], message="Schedule retrieved successfully")
    data = await get_schedule(workspace_id, db, start_date, end_date)
    return success(data, message="Schedule retrieved successfully")


@router.get(
    "/completed",
    response_model=APIResponse[list[CompletedInterviewItem]],
    status_code=status.HTTP_200_OK,
)
async def get_dashboard_completed(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    """Return recently completed interview sessions with scores.

    Powers the completed sessions panel on the dashboard.
    """
    workspace_id = await get_user_workspace(db, user.id)
    if workspace_id is None:
        return success([], message="Completed sessions retrieved successfully")
    data = await get_completed(workspace_id, db)
    return success(data, message="Completed sessions retrieved successfully")
