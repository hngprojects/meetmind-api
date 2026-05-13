import logging
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.responses import APIError, success
from app.db.session import get_session
from app.services.dashboard import get_live_counts, get_live_interviews

router = APIRouter()
logger = logging.getLogger(__name__)


async def _resolve_workspace(user: CurrentUser, db: AsyncSession) -> uuid.UUID:
    """Resolve the workspace the current user belongs to.

    Reuses the same membership check pattern as the interview service so
    the dashboard is scoped to exactly the workspace the user operates in.

    Raises:
        APIError: 403 if the user has no workspace membership.
    """
    from sqlalchemy import select

    from app.models.workspace import WorkspaceMember

    result = await db.execute(
        select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user.id)
    )
    workspace_id = result.scalar_one_or_none()

    if workspace_id is None:
        raise APIError(
            "You do not belong to any workspace",
            status_code=status.HTTP_403_FORBIDDEN,
            code="no_workspace_membership",
        )

    return workspace_id


@router.get("/live", status_code=status.HTTP_200_OK)
async def get_dashboard_live(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Return a count breakdown of all interviews in the workspace by status.

    Powers the summary cards at the top of the dashboard:
    total, in_progress, scheduled, completed, needs_attention.

    Args:
        user: The authenticated user — workspace is resolved from membership.
        db: Async database session.

    Returns:
        A standardized success envelope with the status count breakdown.

    Raises:
        APIError: 403 if the user has no workspace membership.
    """
    workspace_id = await _resolve_workspace(user, db)
    counts = await get_live_counts(workspace_id, db)
    return success(
        counts.model_dump(),
        message="Dashboard live counts retrieved successfully",
    )


@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_dashboard_stats(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Return all currently in-progress interviews for the Live Now panel.

    Each item includes candidate name, role title, elapsed time in seconds
    (null when scheduled_start is missing), and question progress.

    Args:
        user: The authenticated user — workspace is resolved from membership.
        db: Async database session.

    Returns:
        A standardized success envelope containing live_interviews list.

    Raises:
        APIError: 403 if the user has no workspace membership.
    """
    workspace_id = await _resolve_workspace(user, db)
    stats = await get_live_interviews(workspace_id, db)
    return success(
        stats.model_dump(mode="json"),
        message="Dashboard stats retrieved successfully",
    )
