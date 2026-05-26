from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
import uuid

from app.api.deps import DBSession, CurrentUser
from app.models.user import User
from app.services.bot_service import BotService
from sdk.bot_manager import bot_manager
from sdk.db import SDKSessionLocal

router = APIRouter()


class BotJoinRequest(BaseModel):
    interview_id: uuid.UUID
    meeting_url: str
    bot_name: str = "MeetMind"
    platform: str = "google_meet"


class SpeakRequest(BaseModel):
    text: str


@router.post("/bot/join")
async def bot_join(
    req: BotJoinRequest,
    db: DBSession,
    # current_user: CurrentUser,
):
    """
    Start a bot session and join a meeting.
    
    The bot will:
    1. Join the meeting and verify mic access
    2. Listen to transcript events (STT, captions, etc.)
    3. Generate AI responses automatically when human speech is detected
    4. Speak responses autonomously via the event handler
    
    The sync SDK DB session is kept open for the duration of the bot session
    and is automatically closed when the session ends.
    """
    sync_db = SDKSessionLocal()
    service = BotService(async_db=db, sync_db=sync_db)
    result = await service.join_meeting(
        interview_id=req.interview_id,
        meeting_url=req.meeting_url,
        bot_name=req.bot_name,
        platform=req.platform,
    )
    return result


@router.post("/bot/leave/{session_id}")
async def bot_leave(
    session_id: str,
    db: DBSession,
    # current_user: CurrentUser,
):
    """Stop a bot session."""
    service = BotService(async_db=db)
    await service.leave_meeting(session_id)
    return {"status": "stopped", "session_id": session_id}


@router.post("/bot/speak/{session_id}")
async def bot_speak(
    session_id: str,
    req: SpeakRequest,
    db: DBSession,
    # current_user: CurrentUser,
):
    """
    FALLBACK ONLY: Manually trigger the bot to speak.
    
    This endpoint is provided for manual testing and edge cases.
    In normal operation, the bot generates and speaks responses autonomously
    in response to transcript events (TranscriptEvent handler).
    """
    service = BotService(async_db=db)
    await service.speak(session_id, req.text)
    return {"status": "speaking", "text": req.text}


@router.get("/bot/sessions")
async def list_bot_sessions(
    # current_user: CurrentUser,
):
    return bot_manager.list_sessions()