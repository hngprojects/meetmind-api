"""Interview, session management , candidate, transcript, summary,
and scorecard endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.responses import paginated, success
from app.db.session import get_session
from app.schemas.interview import CreateInterviewRequest
from app.services.interview import InterviewService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_interview(
    payload: CreateInterviewRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Create a new interview session with context.

    Creates a candidate record, an interview session in ``draft`` status,
    and an interview summary holding the job description and scoring rubric.

    Args:
        payload: Validated interview creation payload.
        user: The authenticated user — becomes the interviewer.
        db: Async database session.

    Returns:
        A standardized success envelope with the created interview session.

    Raises:
        APIError: 500 for any unexpected failure.
    """
    interview = await InterviewService.create_interview(payload, db, user)
    return success(
        interview.model_dump(mode="json"),
        message="Interview session created successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.get("", status_code=status.HTTP_200_OK)
async def list_interviews(
    user: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
):
    interviews = await InterviewService.list_interviews(db, user, status_filter)
    total = len(interviews)
    start = (page - 1) * page_size
    end = start + page_size
    rows = [item.model_dump(mode="json") for item in interviews[start:end]]
    return paginated(
        rows,
        page=page,
        page_size=page_size,
        total=total,
        message="Interview sessions retrieved successfully",
    )


@router.get("/{interview_id}", status_code=status.HTTP_200_OK)
async def get_interview(
    interview_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Retrieve an interview session by ID.

    Only returns sessions where the authenticated user is the interviewer.

    Args:
        interview_id: UUID of the interview to retrieve.
        user: The authenticated user.
        db: Async database session.

    Returns:
        A standardized success envelope with the interview session data.

    Raises:
        APIError: 404 if the interview does not exist or belongs to another user.
    """
    interview = await InterviewService.get_interview(interview_id, db, user)
    return success(
        interview.model_dump(mode="json"),
        message="Interview session retrieved successfully",
    )


@router.patch("/{interview_id}/confirm", status_code=status.HTTP_200_OK)
async def confirm_interview(
    interview_id: uuid.UUID, user: CurrentUser, db: AsyncSession = Depends(get_session)
):
    interview = await InterviewService.confirm_interview(interview_id, db, user)
    return success(
        interview.model_dump(mode="json"),
        message="Interview session confirmed successfully",
    )


@router.patch("/{interview_id}/complete", status_code=status.HTTP_200_OK)
async def complete_interview(
    interview_id: uuid.UUID, user: CurrentUser, db: AsyncSession = Depends(get_session)
):
    interview = await InterviewService.mark_interview_as_completed(
        interview_id, db, user
    )
    return success(
        interview.model_dump(mode="json"),
        message="Interview session completed successfully",
    )


@router.patch("/{interview_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_interview(
    interview_id: uuid.UUID, user: CurrentUser, db: AsyncSession = Depends(get_session)
):
    interview = await InterviewService.mark_interview_as_cancelled(
        interview_id, db, user
    )
    return success(
        interview.model_dump(mode="json"),
        message="Interview session cancelled successfully",
    )
