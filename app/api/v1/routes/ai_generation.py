"""Routes to trigger AI generation for interviews."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import success
from app.db.session import get_session
from app.schemas.chat import AskRequest, RespondRequest
from app.services.ai_generation_service import AIGenerationService
from app.services.interview import InterviewService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{interview_id}/generate-question")
async def generate_question(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
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
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    next_question = await AIGenerationService.record_response(
        interview_id=interview_id,
        content=payload.content,
        user=user,
        db=db,
    )
    return success({"response": next_question}, message="Response recorded")


@router.post("/{interview_id}/complete")
async def complete_interview(
    interview_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    interview = await AIGenerationService._get_interview_or_404(interview_id, user, db)
    await AIGenerationService.complete_interview(
        interview_id=interview_id,
        user=user,
        db=db,
    )
    background_tasks.add_task(
        AIGenerationService.generate_assessment,
        interview_id=interview_id,
    )

    try:
        await NotificationService.create(
            db=db,
            user_id=user.id,
            type="report",
            title="Interview Completed",
            description=f"{interview.role_title or 'Interview'}",
            action_url=f"/interviews/{interview_id}",
        )
    except Exception:
        logger.exception("Failed to create completion notification")

    return success(
        {"status": "completed"},
        message="Interview completed, assessment generation started",
    )


@router.post("/{interview_id}/chat")
async def ask_question(
    interview_id: uuid.UUID,
    payload: AskRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    result = await AIGenerationService.send_chat_message(
        interview_id=interview_id,
        content=payload.query,
        user=user,
        db=db,
    )
    return success(result, message="Query answered")


@router.post("/{interview_id}/summary/retry", status_code=status.HTTP_200_OK)
async def retry_interview_summary(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.retry_summary(interview_id, db, user)
    background_tasks.add_task(
        AIGenerationService.generate_assessment,
        interview_id=interview_id,
    )

    try:
        interview = await AIGenerationService._get_interview_or_404(
            interview_id, user, db
        )
        await NotificationService.create(
            db=db,
            user_id=user.id,
            type="report",
            title="Summary Regeneration Started",
            description=f"{interview.role_title or 'Interview'}",
            action_url=f"/interviews/{interview_id}",
        )
    except Exception:
        logger.exception("Failed to create retry notification")

    return success(result, message="Summary retry started")


@router.post("/{interview_id}/summary/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_interview_summary(
    interview_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    interview = await AIGenerationService._get_interview_or_404(interview_id, user, db)

    background_tasks.add_task(
        AIGenerationService.generate_assessment,
        interview_id=interview_id,
    )

    try:
        await NotificationService.create(
            db=db,
            user_id=user.id,
            type="report",
            title="Summary Generation Started",
            description=f"{interview.role_title or 'Interview'}",
            action_url=f"/interviews/{interview_id}",
        )
    except Exception:
        logger.exception("Failed to create generation notification")

    return success(
        {"status": "generating"},
        message="Assessment generation started",
        status_code=status.HTTP_202_ACCEPTED,
    )
