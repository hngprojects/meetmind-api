"""LiveKit API routes for token generation, config, and results."""

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from livekit import api
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.responses import APIError
from app.db.session import get_session
from app.models.interview import Candidate, Interview, InterviewSession
from app.services.interview import InterviewService
from app.services.notification_service import NotificationService

router = APIRouter()
logger = logging.getLogger(__name__)

# Schema-compliant sandbox fallback for developer local testing
DEFAULT_INTERVIEW_CONFIG = {
    "role": "Software Engineer",
    "intro": "an automated first-round screening interview",
    "candidateName": "Test Candidate",
    "durationMinutes": 20,
    "closing": "Thanks for your time. A recruiter will follow up with next steps.",
    "questions": [
        {
            "text": (
                "Walk me through a backend system you've built that you're proud of."
            ),
            "followUpHint": "Probe scale, their contribution, and trade-offs.",
            "maxFollowUps": 2,
        },
        {
            "text": (
                "How do you handle database migrations in a production environment?"
            ),
            "followUpHint": (
                "Probe migration tools, zero-downtime strategies, and rollbacks."
            ),
            "maxFollowUps": 2,
        },
    ],
    "rubric": [
        {
            "name": "Technical Depth",
            "description": "Real, hands-on software engineering knowledge.",
            "weight": 3,
        },
        {
            "name": "Communication",
            "description": "Clear and structured explanations.",
            "weight": 2,
        },
    ],
}


class TranscriptTurnRequest(BaseModel):
    speaker: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1)
    sequence_no: int = Field(..., ge=1)
    speaker_name: str | None = None
    timestamp_sec: int | None = None
    is_ai_question: bool = False


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise APIError(
            "Invalid ID format. Must be a valid UUID.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_id",
        )


@router.post("/{interview_id}/token")
async def generate_token(
    interview_id: str, request: Request, db: AsyncSession = Depends(get_session)
):
    """Generate a LiveKit access token for a participant to join an interview."""
    body = await request.json()

    is_test_room = interview_id == "test-room"
    candidate_name = "Candidate"

    if not is_test_room:
        interview_uuid = _parse_uuid(interview_id)
        interview = await db.get(Interview, interview_uuid)
        if not interview:
            raise APIError(
                "Interview not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="interview_not_found",
            )

        if interview.status == "completed":
            raise APIError(
                "Interview is already completed",
                status_code=status.HTTP_400_BAD_REQUEST,
                code="interview_already_completed",
            )

        candidate = (
            await db.get(Candidate, interview.candidate_id)
            if interview.candidate_id
            else None
        )
        candidate_name = candidate.full_name if candidate else "Candidate"
    else:
        candidate_name = body.get("participant_name", "Test User")

    participant_name = candidate_name
    participant_identity = f"candidate_{uuid.uuid4().hex[:8]}"

    if not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        raise APIError(
            "LiveKit credentials not configured",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="liveKit_credentials_are_not_configured",
        )

    token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    token.with_identity(participant_identity).with_name(participant_name)
    token.with_grants(
        api.VideoGrants(
            room_join=True,
            room=interview_id,
        )
    )

    # Return connection details in the format expected by the frontend ViewController
    return {
        "serverUrl": settings.LIVEKIT_URL or "wss://your-project.livekit.cloud",
        "roomName": interview_id,
        "participantName": participant_name,
        "participantToken": token.to_jwt(),
    }


@router.get("/{interview_id}/config")
async def get_agent_config(interview_id: str, db: AsyncSession = Depends(get_session)):
    """The LiveKit agent calls this to get full interview setup."""
    if interview_id == "test-room":
        return DEFAULT_INTERVIEW_CONFIG

    config = await InterviewService.get_agent_config(_parse_uuid(interview_id), db)
    return config


@router.post("/{interview_id}/transcript/turn")
async def post_transcript_turn(
    interview_id: str,
    payload: TranscriptTurnRequest,
    db: AsyncSession = Depends(get_session),
):
    """Persist a single transcript turn during a live LiveKit interview."""
    data, status_code = await InterviewService.append_transcript_turn(
        _parse_uuid(interview_id), payload.model_dump(), db
    )
    return JSONResponse(status_code=status_code, content=data)


@router.post("/{session_id}/result")
async def post_result(
    session_id: str, request: Request, db: AsyncSession = Depends(get_session)
):
    """The LiveKit agent posts the transcript and report here when done."""
    body = await request.json()
    transcript = body.get("transcript", [])
    report = body.get("report")

    is_test_room = session_id == "test-room"
    if is_test_room:
        return {"status": "success", "message": "Test result received successfully"}

    result_uuid = _parse_uuid(session_id)

    interview = await db.get(Interview, result_uuid)
    if interview and interview.session_id:
        session = await db.get(InterviewSession, interview.session_id)
    else:
        query = select(InterviewSession).where(InterviewSession.id == result_uuid)
        result = await db.execute(query)
        session = result.scalar_one_or_none()

    if not session:
        raise APIError(
            "Session not found",
            status_code=status.HTTP_404_NOT_FOUND,
            code="session_not_found",
        )

    # Update session in the database
    session.transcript_json = json.dumps(transcript) if transcript is not None else None
    session.report_json = json.dumps(report) if report is not None else None
    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)
    if interview:
        interview.status = "completed"

    await db.commit()

    try:
        interview_result = await db.execute(
            select(Interview).where(Interview.session_id == result_uuid)
        )
        interview = interview_result.scalar_one_or_none()
        if interview:
            await NotificationService.create(
                db=db,
                user_id=interview.interviewer_id,
                type="report",
                title="Interview Summary Ready",
                action_url=f"/interviews/{interview.id}",
            )
    except Exception:
        logger.exception("Failed to create report notification")

    return {"status": "success", "message": "Result saved successfully"}
