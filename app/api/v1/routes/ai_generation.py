"""Routes to trigger AI generation for interviews."""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.responses import success
from app.db.session import get_session
from app.services.ai_generation_service import AIGenerationService

router = APIRouter()


class RespondRequest(BaseModel):
    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1)


@router.post("/{interview_id}/generate-question")
async def generate_question(
    interview_id: uuid.UUID,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Generate the next AI interview question based on context and history."""
    question = await AIGenerationService.generate_next_question(
        interview_id=interview_id,
        db=db,
        user=user,
    )
    return success(
        {"question": question},
        message="Question generated",
        status_code=status.HTTP_200_OK,
    )


@router.post("/{interview_id}/respond")
async def respond_to_question(
    interview_id: uuid.UUID,
    payload: RespondRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Record a candidate response and generate the next question."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models.interview import (
        Interview,
        InterviewTranscript,
        InterviewTranscriptTurn,
    )

    interview = (
        await db.execute(
            select(Interview).where(
                Interview.id == interview_id,
                Interview.interviewer_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if not interview:
        from app.core.responses import APIError

        raise APIError(
            "Interview not found",
            status_code=404,
            code="interview_not_found",
        )

    transcript = (
        await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
    ).scalar_one_or_none()

    if transcript is None:
        transcript = InterviewTranscript(
            interview_id=interview_id, status="processing"
        )
        db.add(transcript)
        await db.flush()

    last_seq = (
        await db.execute(
            select(InterviewTranscriptTurn.sequence_no)
            .where(InterviewTranscriptTurn.transcript_id == transcript.id)
            .order_by(InterviewTranscriptTurn.sequence_no.desc())
            .limit(1)
        )
    ).scalar_one_or_none() or 0

    turn = InterviewTranscriptTurn(
        transcript_id=transcript.id,
        speaker="candidate",
        speaker_name="Candidate",
        content=payload.content,
        sequence_no=last_seq + 1,
        is_ai_question=False,
        timestamp_sec=int(datetime.now(timezone.utc).timestamp()),
    )
    db.add(turn)

    next_question = await AIGenerationService.generate_next_question(
        interview_id=interview_id,
        db=db,
        user=user,
    )

    return success(
        {"response": next_question},
        message="Response recorded",
        status_code=status.HTTP_200_OK,
    )


@router.post("/{interview_id}/complete")
async def complete_interview(
    interview_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Mark interview complete and generate assessment in background."""
    from sqlalchemy import select

    from app.models.interview import Interview

    interview = (
        await db.execute(
            select(Interview).where(
                Interview.id == interview_id,
                Interview.interviewer_id == user.id,
            )
        )
    ).scalar_one_or_none()

    if not interview:
        from app.core.responses import APIError

        raise APIError(
            "Interview not found",
            status_code=404,
            code="interview_not_found",
        )

    interview.status = "completed"
    await db.flush()

    background_tasks.add_task(
        AIGenerationService.generate_assessment,
        interview_id=interview_id,
        db=db,
    )

    return success(
        {"status": "completed"},
        message="Interview completed, assessment generation started",
        status_code=status.HTTP_200_OK,
    )


@router.post("/{interview_id}/ask")
async def ask_question(
    interview_id: uuid.UUID,
    payload: AskRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_session),
):
    """Ask a natural language question about an interview session."""
    answer = await AIGenerationService.answer_query(
        interview_id=interview_id,
        query=payload.query,
        user=user,
        db=db,
    )
    return success(
        {"answer": answer},
        message="Query answered",
        status_code=status.HTTP_200_OK,
    )
