from fastapi import APIRouter, HTTPException, Request
from livekit import api

from app.core.config import settings

router = APIRouter()

# Stubbed in-memory or default configuration since we do not have a full DB model yet
DEFAULT_INTERVIEW = {
    "role": "Software Engineer",
    "questions": ["Tell me about your experience.", "What is your strongest skill?"],
    "duration_minutes": 30,
    "rubric": "Evaluate their technical experience.",
}


@router.post("/{session_id}/token")
async def generate_token(session_id: str, request: Request):
    """Generate a LiveKit access token for a participant to join a session."""
    body = await request.json()
    participant_name = body.get("participant_name", "Candidate")

    if not settings.LIVEKIT_API_KEY or not settings.LIVEKIT_API_SECRET:
        raise HTTPException(
            status_code=500, detail="LiveKit credentials are not configured"
        )

    token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
    token.with_identity(participant_name).with_name(participant_name)
    token.with_grants(
        api.VideoGrants(
            room_join=True,
            room=session_id,
        )
    )

    return {"token": token.to_jwt()}


@router.get("/{session_id}/config")
async def get_agent_config(session_id: str):
    """The LiveKit agent calls this to get interview setup."""
    # In a real app, you would query the database using the session_id
    # to fetch custom questions, role, and rubric.
    return DEFAULT_INTERVIEW


@router.post("/{session_id}/result")
async def post_result(session_id: str, request: Request):
    """The LiveKit agent posts the transcript and report here when done."""
    body = await request.json()
    # In a real app, you would save body["transcript"] and body["report"]
    # to the database linked to the session_id.
    _ = body  # body consumed; DB persistence to be wired up

    return {"status": "success", "message": "Result saved successfully"}
