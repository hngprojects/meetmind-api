"""LiveKit API routes for token generation, config, and results."""

import logging
import uuid

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from livekit import api
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.responses import APIError
from app.db.session import get_session
from app.models.interview import Candidate, Interview
from app.schemas.livekit import (
    InterviewResultResponse,
    LiveKitTokenResponse,
    TranscriptTurnRequest,
    TranscriptTurnResponse,
)
from app.services.interview import InterviewService

router = APIRouter()
logger = logging.getLogger(__name__)

# Schema-compliant sandbox fallback for developer local testing
DEFAULT_INTERVIEW_CONFIG = {
    "role": "Interview Candidate",
    "intro": "an automated first-round screening interview",
    "candidateName": "Test Candidate",
    "durationMinutes": 20,
    "closing": "Thanks for your time. A recruiter will follow up with next steps.",
    "questions": [
        {
            "text": ("Walk me through work you have done that best matches this role."),
            "followUpHint": "Probe scope, their contribution, outcomes, and trade-offs.",
            "maxFollowUps": 2,
        },
        {
            "text": ("Tell me about a challenging project and how you approached it."),
            "followUpHint": (
                "Probe problem solving, collaboration, constraints, and impact."
            ),
            "maxFollowUps": 2,
        },
    ],
    "rubric": [
        {
            "name": "Role Fit",
            "description": "Relevant hands-on experience for the target role.",
            "weight": 3,
        },
        {
            "name": "Communication",
            "description": "Clear and structured explanations.",
            "weight": 2,
        },
    ],
}


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        raise APIError(
            "Invalid ID format. Must be a valid UUID.",
            status_code=status.HTTP_400_BAD_REQUEST,
            code="invalid_id",
        )


@router.post("/{interview_id}/token", response_model=LiveKitTokenResponse)
async def generate_token(
    interview_id: str, request: Request, db: AsyncSession = Depends(get_session)
):
    """Generate a LiveKit access token for a participant to join an interview."""
    interview_id = interview_id.strip()
    try:
        body = await request.json()
    except Exception:
        body = {}

    is_test_room = interview_id == "test-room"
    candidate_name = "Candidate"

    if not is_test_room:
        interview_uuid = _parse_uuid(interview_id)
        interview = await db.get(Interview, interview_uuid)
        if not interview:
            res = await db.execute(
                select(Interview).where(Interview.session_id == interview_uuid)
            )
            interview = res.scalar_one_or_none()
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


@router.get("/{interview_id}/config", response_model=dict)
async def get_agent_config(interview_id: str, db: AsyncSession = Depends(get_session)):
    """The LiveKit agent calls this to get full interview setup."""
    interview_id = interview_id.strip()
    if interview_id == "test-room":
        return DEFAULT_INTERVIEW_CONFIG
    config = await InterviewService.get_agent_config(_parse_uuid(interview_id), db)
    return config


@router.post("/{interview_id}/transcript/turn", response_model=TranscriptTurnResponse)
async def post_transcript_turn(
    interview_id: str,
    payload: TranscriptTurnRequest,
    db: AsyncSession = Depends(get_session),
):
    """Persist a single transcript turn during a live LiveKit interview."""
    interview_id = interview_id.strip()
    data, status_code = await InterviewService.append_transcript_turn(
        _parse_uuid(interview_id), payload.model_dump(), db
    )
    return JSONResponse(status_code=status_code, content=data)


@router.post("/{interview_id}/result", response_model=InterviewResultResponse)
async def post_result(
    interview_id: str, request: Request, db: AsyncSession = Depends(get_session)
):
    """The LiveKit agent posts the transcript and report here when done."""
    interview_id = interview_id.strip()
    try:
        body = await request.json()
    except Exception:
        body = {}
    transcript = body.get("transcript", [])
    report = body.get("report")

    is_test_room = interview_id == "test-room"
    if is_test_room:
        return {"status": "success", "message": "Result saved successfully"}

    interview_uuid = _parse_uuid(interview_id)

    res = await InterviewService.process_interview_result(
        interview_uuid, transcript, report, db
    )
    return res
