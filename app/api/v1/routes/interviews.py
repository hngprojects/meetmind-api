"""Interview, session management , candidate, transcript, summary,
and scorecard endpoints."""

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import VerifiedUser
from app.core.responses import APIResponse, paginated, success
from app.db.session import get_session
from app.schemas.interview import (
    AIConfigUpdateResponse,
    ContextUpdateResponse,
    CreateInterviewRequest,
    CriteriaUpdateResponse,
    InterviewConfirmResponse,
    InterviewListItem,
    InterviewProfileResponse,
    InterviewResponse,
    InterviewScorecardResponse,
    InterviewSessionStatusResponse,
    InterviewSummaryDetailResponse,
    RejoinSessionResponse,
    TranscriptStopResponse,
    UpdateAIConfigRequest,
    UpdateContextRequest,
    UpdateCriteriaRequest,
)
from app.services.chat_history import ChatHistoryService
from app.services.email_service import send_interview_link_email
from app.services.interview import InterviewService
from app.services.notification_service import NotificationService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=APIResponse[InterviewResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_interview(
    payload: CreateInterviewRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    interview = await InterviewService.create_interview(payload, db, user)

    try:
        description = f"{interview.candidate_name} - {interview.role_title}"
        if interview.scheduled_date:
            description += f" - {interview.scheduled_date}"
        await NotificationService.create(
            db=db,
            user_id=user.id,
            type="meeting",
            title="Interview Scheduled",
            description=description,
            action_url=f"/interviews/{interview.id}",
        )
    except Exception:
        logger.exception("Failed to create meeting notification")

    return success(
        interview.model_dump(mode="json"),
        message="Interview session created successfully",
        status_code=status.HTTP_201_CREATED,
    )


@router.get(
    "",
    response_model=APIResponse[list[InterviewListItem]],
    status_code=status.HTTP_200_OK,
)
async def list_interviews(
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
    page: int = 1,
    page_size: int = 20,
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
):
    rows, total = await InterviewService.list_interviews(
        db, user, page, page_size, status, search
    )
    items = [
        InterviewListItem(
            id=i.id,
            candidate_name=full_name,
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


@router.get(
    "/{interview_id}",
    response_model=APIResponse[InterviewResponse],
    status_code=status.HTTP_200_OK,
)
async def get_interview(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    interview = await InterviewService.get_interview(interview_id, db, user)
    return success(
        interview.model_dump(mode="json"),
        message="Interview session retrieved successfully",
    )


@router.post(
    "/{interview_id}/confirm",
    response_model=APIResponse[InterviewConfirmResponse],
    status_code=status.HTTP_200_OK,
)
async def confirm_interview(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.confirm_interview(interview_id, db, user)
    return success(result, message="Interview confirmed successfully")


@router.patch(
    "/{interview_id}/cancel",
    response_model=APIResponse[InterviewResponse],
    status_code=status.HTTP_200_OK,
)
async def cancel_interview(
    interview_id: uuid.UUID, user: VerifiedUser, db: AsyncSession = Depends(get_session)
):
    interview = await InterviewService.cancel_interview(interview_id, db, user)

    try:
        desc = f"{interview.candidate_name} - {interview.role_title}"
        if interview.scheduled_date:
            desc += f" - {interview.scheduled_date}"
        await NotificationService.create(
            db=db,
            user_id=user.id,
            type="meeting",
            title="Interview Cancelled",
            description=desc,
            action_url=f"/interviews/{interview.id}",
        )
    except Exception:
        logger.exception("Failed to create cancellation notification")

    return success(
        interview.model_dump(mode="json"),
        message="Interview session cancelled successfully",
    )


@router.get("/{interview_id}/chat/history", status_code=status.HTTP_200_OK)
async def get_chat_history(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    history = await ChatHistoryService.get_chat_history(interview_id, db, user)
    return success(
        history.model_dump(mode="json"),
        message="Chat history retrieved successfully",
    )


@router.get("/{interview_id}/transcript", status_code=status.HTTP_200_OK)
async def get_transcript(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    transcript = await ChatHistoryService.get_transcript(interview_id, db, user)
    return success(
        transcript.model_dump(mode="json"),
        message="Transcript retrieved",
    )


@router.get("/{interview_id}/transcript/export", status_code=status.HTTP_200_OK)
async def export_transcript(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    lines = await ChatHistoryService.get_transcript_export(interview_id, db, user)
    filename = f"transcript_{interview_id}.txt"
    return StreamingResponse(
        content=iter(lines),
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post(
    "/{interview_id}/transcript/stop",
    response_model=APIResponse[TranscriptStopResponse],
    status_code=status.HTTP_200_OK,
)
async def stop_transcript(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.stop_transcript(interview_id, db, user)
    return success(
        result,
        message="Interview transcript stopped successfully",
    )


@router.put(
    "/{interview_id}/criteria",
    response_model=APIResponse[CriteriaUpdateResponse],
    status_code=status.HTTP_200_OK,
)
async def update_criteria(
    interview_id: uuid.UUID,
    payload: UpdateCriteriaRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.update_interview_criteria(
        interview_id, payload, db, user
    )
    return success(result, message="Criteria updated successfully")


@router.put(
    "/{interview_id}/context",
    response_model=APIResponse[ContextUpdateResponse],
    status_code=status.HTTP_200_OK,
)
async def update_context(
    interview_id: uuid.UUID,
    payload: UpdateContextRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.update_context(interview_id, payload, db, user)
    return success(result, message="Context updated successfully")


@router.put(
    "/{interview_id}/session-config",
    response_model=APIResponse[AIConfigUpdateResponse],
    status_code=status.HTTP_200_OK,
)
async def update_ai_config(
    interview_id: uuid.UUID,
    payload: UpdateAIConfigRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    result = await InterviewService.update_session_config(
        interview_id, payload, db, user
    )
    return success(result, message="AI config updated successfully")


@router.get(
    "/{interview_id}/summary",
    response_model=APIResponse[InterviewSummaryDetailResponse],
    status_code=status.HTTP_200_OK,
)
async def get_interview_summary(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    summary = await InterviewService.get_summary(interview_id, db, user)
    return success(summary, message="Summary retrieved successfully")


@router.get(
    "/{interview_id}/session",
    response_model=APIResponse[InterviewSessionStatusResponse],
    status_code=status.HTTP_200_OK,
)
async def get_interview_session(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    session = await InterviewService.get_session_status(interview_id, db, user)
    return success(session, message="Session status retrieved")


@router.get(
    "/{interview_id}/scorecard",
    response_model=APIResponse[InterviewScorecardResponse],
    status_code=status.HTTP_200_OK,
)
async def get_interview_scorecard(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    """Retrieve scorecard evaluated details for an interview."""
    scorecard = await InterviewService.get_scorecard(interview_id, db, user)
    return success(scorecard, message="Scorecard retrieved successfully")


@router.get(
    "/{interview_id}/profile",
    response_model=APIResponse[InterviewProfileResponse],
    status_code=status.HTTP_200_OK,
)
async def get_interview_profile(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    """Retrieve candidate profile scheduling and metadata details."""
    profile = await InterviewService.get_profile(interview_id, db, user)
    return success(profile, message="Profile retrieved successfully")


@router.post(
    "/{interview_id}/session/rejoin",
    response_model=APIResponse[RejoinSessionResponse],
    status_code=status.HTTP_200_OK,
)
async def rejoin_interview_session(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_session),
):
    """Idempotently signal reconnection to an active interview room."""
    result = await InterviewService.rejoin_session(interview_id, db, user)
    return success(result, message="Session rejoin successfully requested")


@router.post("/{interview_id}/send-link", status_code=status.HTTP_200_OK)
async def send_interview_link(
    interview_id: uuid.UUID,
    user: VerifiedUser,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
    email: str | None = None,
):
    """Send the interview session/LiveKit invitation link via email.
    
    If an optional `email` query param is provided, the invite will be sent to that address. 
    Otherwise, it defaults to the verified user's registered email address.
    """
    interview = await InterviewService.get_interview(interview_id, db, user)
    
    recipient_email = email or user.email
    recipient_name = user.name if not email else None
    
    await send_interview_link_email(
        email=recipient_email,
        name=recipient_name,
        interview_id=interview.id,
        role_title=interview.role_title or "Candidate Screening",
        background_tasks=background_tasks,
    )
    
    return success(
        message=f"Interview link email sent successfully to {recipient_email}"
    )

