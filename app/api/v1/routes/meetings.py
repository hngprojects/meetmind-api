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
    current_user: CurrentUser,
):
    # Create a synchronous SDK DB session for the bot/SDK repository.
    # Keep it open for the duration of the bot session, then let the bot
    # manager cleanup close it when the session ends.
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
    current_user: CurrentUser,
):
    service = BotService(async_db=db)
    await service.leave_meeting(session_id)
    return {"status": "stopped", "session_id": session_id}


@router.post("/bot/speak/{session_id}")
async def bot_speak(
    session_id: str,
    req: SpeakRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    service = BotService(async_db=db)
    await service.speak(session_id, req.text)
    return {"status": "speaking", "text": req.text}


@router.get("/bot/sessions")
async def list_bot_sessions(
    current_user: CurrentUser,
):
    return bot_manager.list_sessions()