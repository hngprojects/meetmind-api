"""Interview, session management , candidate, transcript, summary,
and scorecard endpoints."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.responses import paginated, success
from app.db.session import get_session
from app.schemas.interview import (
    AIReplyRequest,
    AISummaryRequest,
    AskMindRequest,
    CreateInterviewRequest,
    InterviewListItem,
    UpdateAIConfigRequest,
    UpdateContextRequest,
    UpdateCriteriaRequest,
)
from app.services.ai_integration_service import AIIntegrationService
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


@router.get("", status_code=status.HTTP_200_OK)
async def list_interviews(
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
    page: int = 1,
    page_size: int = 20,
):

    rows, total = await InterviewService.list_interviews(db, user, page, page_size)
    items = [
        InterviewListItem(
            id=i.id,
            candidate_name=full_name,  # resolved below
            role_title=i.role_title,
            platform=i.platform,
            status=i.status,
            scheduled_start=i.scheduled_start,
            participation_mode=i.participation_mode,
            created_at=i.created_at,
        ).model_dump(mode="json")
        for i, full_name in rows
    ]
    return paginated(
        items, page=page, page_size=page_size, total=total, message="Sessions retrieved"
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


@router.post("/{interview_id}/confirm", status_code=status.HTTP_200_OK)
async def confirm_interview(
    interview_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.confirm_interview(interview_id, db, user)
    return success(result, message="Interview confirmed successfully")


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


@router.put("/{interview_id}/context", status_code=status.HTTP_200_OK)
async def update_context(
    interview_id: uuid.UUID,
    payload: UpdateContextRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.update_context(interview_id, payload, db, user)
    return success(result, message="Context updated successfully")


@router.put("/{interview_id}/session-config", status_code=status.HTTP_200_OK)
async def update_ai_config(
    interview_id: uuid.UUID,
    payload: UpdateAIConfigRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.update_session_config(
        interview_id, payload, db, user
    )
    return success(result, message="AI config updated successfully")


@router.post("/{interview_id}/ai/reply", status_code=status.HTTP_200_OK)
async def generate_ai_reply(
    interview_id: uuid.UUID,
    payload: AIReplyRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Generate an AI reply during an interview session.

    Calls AIIntegrationService.generate_reply and persists the AI turn.
    """
    try:
        ai_output = await AIIntegrationService.generate_reply(
            db=db,
            interview_id=interview_id,
            session_id=payload.session_id,
            candidate_id=payload.candidate_id,
            job_description=payload.job_description,
            scoring_rubric=payload.scoring_rubric,
            transcript_text=payload.transcript_text,
            user=user,
        )
        return success(ai_output, message="AI reply generated successfully")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"AI reply generation failed: {str(e)}"
        )


@router.post("/{interview_id}/ai/summary", status_code=status.HTTP_200_OK)
async def generate_ai_summary(
    interview_id: uuid.UUID,
    payload: AISummaryRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Generate a post-interview summary and scorecard.

    Calls AIIntegrationService.generate_summary and returns structured output.
    """
    try:
        ai_output = await AIIntegrationService.generate_summary(
            db=db,
            interview_id=interview_id,
            candidate_id=payload.candidate_id,
            job_description=payload.job_description,
            scoring_rubric=payload.scoring_rubric,
            transcript_text=payload.transcript_text,
            user=user,
        )
        return success(ai_output, message="AI summary generated successfully")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"AI summary generation failed: {str(e)}"
        )


@router.post("/{interview_id}/ai/ask", status_code=status.HTTP_200_OK)
async def ask_mind(
    interview_id: uuid.UUID,
    payload: AskMindRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Ask MeetMind a question about the candidate or meeting."""
    try:
        ai_output = await AIIntegrationService.answer_query(
            db=db,
            candidate_id=payload.candidate_id,
            interview_id=interview_id,
            query=payload.query,
            user=user,
            transcript_text=payload.transcript_text,
        )
        return success(ai_output, message="AI answered query successfully")
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"AI query answering failed: {str(e)}"
        )
