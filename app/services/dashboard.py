from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Candidate, Interview
from app.schemas.dashboard import (
    DashboardLiveResponse,
    DashboardStatsResponse,
    LiveInterviewItem,
)


async def get_live_counts(
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> DashboardLiveResponse:
    """Return a count breakdown of all interviews in the workspace by status.

    Uses a single aggregation query with conditional counts to avoid
    multiple round-trips to the database.

    Args:
        workspace_id: The workspace to scope the query to.
        db: Active async database session.

    Returns:
        A :class:`DashboardLiveResponse` with counts for every status bucket.
    """
    result = await db.execute(
        select(
            func.count().label("total"),
            func.count().filter(Interview.status == "in_progress").label("in_progress"),
            func.count().filter(Interview.status == "scheduled").label("scheduled"),
            func.count().filter(Interview.status == "completed").label("completed"),
            func.count()
            .filter(Interview.status == "needs_attention")
            .label("needs_attention"),
        ).where(Interview.workspace_id == workspace_id)
    )
    row = result.one()

    return DashboardLiveResponse(
        total=row.total,
        in_progress=row.in_progress,
        scheduled=row.scheduled,
        completed=row.completed,
        needs_attention=row.needs_attention,
    )


async def get_live_interviews(
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> DashboardStatsResponse:
    """Return all currently in-progress interviews for the Live Now panel.

    Joins interviews to candidates to resolve the candidate name.
    elapsed_seconds is computed in Python from scheduled_start so it stays
    accurate without a DB round-trip per poll — and returns None safely
    when scheduled_start is null (see RFC decision log).

    Results are ordered by scheduled_start ascending so the longest-running
    session appears first.

    Args:
        workspace_id: The workspace to scope the query to.
        db: Active async database session.

    Returns:
        A :class:`DashboardStatsResponse` with the list of live interviews.
    """
    result = await db.execute(
        select(
            Interview.id,
            Interview.role_title,
            Interview.scheduled_start,
            Interview.questions_asked,
            Interview.questions_total,
            Candidate.full_name,
        )
        .join(Candidate, Candidate.id == Interview.candidate_id)
        .where(
            Interview.workspace_id == workspace_id,
            Interview.status == "in_progress",
        )
        .order_by(Interview.scheduled_start.asc().nulls_last())
    )
    rows = result.all()

    now = datetime.now(UTC)

    items = [
        LiveInterviewItem(
            interview_id=row.id,
            candidate_name=row.full_name,
            role_title=row.role_title,
            # Compute elapsed in Python. Returns None when scheduled_start
            # is null — frontend renders '--:--' per the RFC contract.
            elapsed_seconds=(
                int((now - row.scheduled_start.replace(tzinfo=UTC)).total_seconds())
                if row.scheduled_start is not None
                else None
            ),
            questions_asked=row.questions_asked,
            questions_total=row.questions_total,
        )
        for row in rows
    ]

    return DashboardStatsResponse(live_interviews=items)
