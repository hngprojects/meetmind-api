"""LiveKit API routes for token generation, config, and results."""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from livekit import api
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.models.interview import InterviewSession

router = APIRouter()

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
                "Walk me through a backend system you've built that "
                "you're proud of."
            ),
            "followUpHint": "Probe scale, their contribution, and trade-offs.",
            "maxFollowUps": 2,
        },
        {
            "text": (
                "How do you handle database migrations in a "
                "production environment?"
            ),
            "followUpHint": (
                "Probe migration tools, zero-downtime strategies, "
                "and rollbacks."
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


@router.post("/{session_id}/token")
async def generate_token(
    session_id: str, request: Request, db: AsyncSession = Depends(get_session)
):
    """Generate a LiveKit access token for a participant to join a session."""
    body = await request.json()

    is_test_room = session_id == "test-room"
    candidate_name = "Candidate"

    if not is_test_room:
        try:
            session_uuid = uuid.UUID(session_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid session ID format. Must be a valid UUID.",
            )

        # Verify session status in the database
        query = select(InterviewSession).where(InterviewSession.id == session_uuid)
        result = await db.execute(query)
        session = result.scalar_one_or_none()

        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
            )
        if session.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Session is already completed",
            )

        candidate_name = session.candidate_name or "Candidate"
    else:
        candidate_name = body.get("participant_name", "Test User")

    participant_name = candidate_name
    participant_identity = f"candidate_{uuid.uuid4().hex[:8]}"

    if not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="LiveKit credentials are not configured",
        )

    token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    token.with_identity(participant_identity).with_name(participant_name)
    token.with_grants(
        api.VideoGrants(
            room_join=True,
            room=session_id,
        )
    )

    # Return connection details in the format expected by the frontend ViewController
    return {
        "serverUrl": settings.LIVEKIT_URL or "wss://your-project.livekit.cloud",
        "roomName": session_id,
        "participantName": participant_name,
        "participantToken": token.to_jwt(),
    }


@router.get("/{session_id}/config")
async def get_agent_config(session_id: str, db: AsyncSession = Depends(get_session)):
    """The LiveKit agent calls this to get interview setup."""
    is_test_room = session_id == "test-room"

    if is_test_room:
        return DEFAULT_INTERVIEW_CONFIG

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session ID format. Must be a valid UUID.",
        )

    query = select(InterviewSession).where(InterviewSession.id == session_uuid)
    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Mark the session as in_progress on first fetch (when agent joins)
    if session.status == "created":
        session.status = "in_progress"
        session.started_at = datetime.now(timezone.utc)
        await db.commit()

    return {
        "role": session.role,
        "intro": session.intro,
        "candidateName": session.candidate_name,
        "durationMinutes": session.duration_minutes,
        "closing": session.closing,
        "questions": (
            json.loads(session.questions_json) if session.questions_json else []
        ),
        "rubric": (json.loads(session.rubric_json) if session.rubric_json else []),
    }


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

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session ID format. Must be a valid UUID.",
        )

    query = select(InterviewSession).where(InterviewSession.id == session_uuid)
    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Update session in the database
    session.transcript_json = json.dumps(transcript) if transcript is not None else None
    session.report_json = json.dumps(report) if report is not None else None
    session.status = "completed"
    session.completed_at = datetime.now(timezone.utc)

    await db.commit()
    return {"status": "success", "message": "Result saved successfully"}
