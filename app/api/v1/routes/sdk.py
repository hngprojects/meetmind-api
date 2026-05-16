from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sdk.db import get_sdk_db
from sdk.providers.zoom_meeting_bridge.bridge import MeetingOutputBridge
from sdk.schemas import CreateSDKSessionRequest, SpeakRequest
from sdk.sdk import MeetMindSDK

router = APIRouter()


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_sdk_session(
    payload: CreateSDKSessionRequest,
    db: Session = Depends(get_sdk_db),
):
    if payload.platform.lower() != "zoom":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only platform='zoom' is supported in this prototype.",
        )
    sdk = MeetMindSDK(db)
    session = sdk.create_zoom_session(
        meeting_id=payload.meeting_id,
        meeting_url=payload.meeting_url,
        agent_name=payload.agent_name,
        context=payload.context,
        wake_words=payload.wake_words,
    )
    return {"status": True, "message": "SDK session created", "data": session.to_dict()}


@router.get("/sessions/{session_id}")
def get_sdk_session(session_id: str, db: Session = Depends(get_sdk_db)):
    session = MeetMindSDK(db).get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="SDK session not found")
    return {"status": True, "message": "SDK session fetched", "data": session.to_dict()}


@router.get("/sessions/{session_id}/transcript")
def get_sdk_transcript(session_id: str, db: Session = Depends(get_sdk_db)):
    sdk = MeetMindSDK(db)
    session = sdk.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="SDK session not found")
    turns = [turn.to_dict() for turn in sdk.get_transcript(session_id)]
    return {
        "status": True,
        "message": "SDK transcript fetched",
        "data": {"session": session.to_dict(), "turns": turns},
    }


@router.post("/sessions/{session_id}/speak", status_code=status.HTTP_202_ACCEPTED)
def speak_in_session(
    session_id: str,
    payload: SpeakRequest,
    db: Session = Depends(get_sdk_db),
):
    session = MeetMindSDK(db).get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="SDK session not found")
    try:
        result = MeetingOutputBridge().speak(session_id=session_id, text=payload.text)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return {"status": True, "message": "Speech request accepted", "data": result}
