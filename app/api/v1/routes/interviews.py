"""Interview, session management , candidate, transcript, summary,
and scorecard endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.responses import success
from app.db.session import get_session
from app.schemas.interview import CreateInterviewRequest, UpdateCriteriaRequest
from app.services.chat_history import ChatHistoryService
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


@router.patch("/{interview_id}/cancel", status_code=status.HTTP_200_OK)
async def cancel_interview(
    interview_id: uuid.UUID, user: CurrentUser, db: AsyncSession = Depends(get_session)
):
    interview = await InterviewService.cancel_interview(interview_id, db, user)
    return success(
        interview.model_dump(mode="json"),
        message="Interview session cancelled successfully",
    )


@router.get("/{interview_id}/chat/history", status_code=status.HTTP_200_OK)
async def get_chat_history(
    interview_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Retrieve the full chat history for an interview session.

    Returns all transcript turns in sequence order. Only returns history
    for interviews where the authenticated user is the interviewer.

    Args:
        interview_id: UUID of the interview to fetch chat history for.
        user: The authenticated user.
        db: Async database session.

    Returns:
        A standardized success envelope with the chat history.

    Raises:
        APIError: 404 if the interview does not exist or belongs to another user.
    """
    history = await ChatHistoryService.get_chat_history(interview_id, db, user)
    return success(
        history.model_dump(mode="json"),
        message="Chat history retrieved successfully",
    )


@router.put("/{interview_id}/criteria", status_code=status.HTTP_200_OK)
async def update_criteria(
    interview_id: uuid.UUID,
    payload: UpdateCriteriaRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Update scorecard criteria for a draft interview.

    Replaces all existing criteria with the provided list. Only allowed
    while the interview is in ``draft`` status.

    Args:
        interview_id: UUID of the interview to update criteria for.
        payload: Validated criteria payload (1–10 items).
        user: The authenticated user.
        db: Async database session.

    Returns:
        A standardized success envelope with the updated criteria list.

    Raises:
        APIError: 404 if the interview does not exist or belongs to another user.
        APIError: 400 if the interview is not in draft status.
    """
    result = await InterviewService.update_interview_criteria(
        interview_id, payload, db, user
    )
    return success(result, message="Criteria updated successfully")
