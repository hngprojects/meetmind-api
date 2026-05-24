"""FastAPI router for managing interview sessions (LiveKit voice screenings)."""

import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.interview import InterviewSession

router = APIRouter()


class QuestionSchema(BaseModel):
    text: str
    followUpHint: Optional[str] = ""
    maxFollowUps: Optional[int] = 2


class RubricCriterionSchema(BaseModel):
    name: str
    description: Optional[str] = ""
    weight: Optional[int] = 1


class SessionCreateSchema(BaseModel):
    role: str
    candidateName: Optional[str] = None
    intro: str
    questions: List[QuestionSchema]
    rubric: List[RubricCriterionSchema]
    durationMinutes: Optional[int] = 20
    closing: Optional[str] = (
        "Thanks for your time. A recruiter will follow up with next steps."
    )


class SessionUpdateSchema(BaseModel):
    role: Optional[str] = None
    candidateName: Optional[str] = None
    intro: Optional[str] = None
    questions: Optional[List[QuestionSchema]] = None
    rubric: Optional[List[RubricCriterionSchema]] = None
    durationMinutes: Optional[int] = None
    closing: Optional[str] = None


def to_dto(session: InterviewSession) -> dict:
    """Convert an InterviewSession row to the frontend expected camelCase DTO."""
    return {
        "id": str(session.id),
        "role": session.role,
        "candidateName": session.candidate_name,
        "intro": session.intro,
        "questions": (
            json.loads(session.questions_json) if session.questions_json else []
        ),
        "rubric": (json.loads(session.rubric_json) if session.rubric_json else []),
        "durationMinutes": session.duration_minutes,
        "closing": session.closing,
        "status": session.status,
        "transcript": (
            json.loads(session.transcript_json) if session.transcript_json else None
        ),
        "report": (json.loads(session.report_json) if session.report_json else None),
        "createdAt": session.created_at.isoformat() if session.created_at else None,
        "startedAt": session.started_at.isoformat() if session.started_at else None,
        "completedAt": (
            session.completed_at.isoformat() if session.completed_at else None
        ),
    }


@router.get("/", status_code=status.HTTP_200_OK)
async def list_sessions(db: AsyncSession = Depends(get_session)):
    """List all interview sessions, ordered by created_at desc."""
    query = select(InterviewSession).order_by(InterviewSession.created_at.desc())
    result = await db.execute(query)
    sessions = result.scalars().all()
    return [to_dto(s) for s in sessions]


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: SessionCreateSchema, db: AsyncSession = Depends(get_session)
):
    """Create a new interview session."""
    role = payload.role.strip()
    intro = payload.intro.strip()
    if not role or not intro or len(payload.questions) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="role, intro, and at least one question are required",
        )

    # Serialize schemas to clean dictionaries
    questions_data = [
        {
            "text": q.text.strip(),
            "followUpHint": q.followUpHint.strip() if q.followUpHint else "",
            "maxFollowUps": q.maxFollowUps if q.maxFollowUps is not None else 2,
        }
        for q in payload.questions
    ]
    rubric_data = [
        {
            "name": r.name.strip(),
            "description": r.description.strip() if r.description else "",
            "weight": r.weight if r.weight is not None else 1,
        }
        for r in payload.rubric
    ]

    session = InterviewSession(
        role=role,
        candidate_name=(
            payload.candidateName.strip() if payload.candidateName else None
        ),
        intro=intro,
        questions_json=json.dumps(questions_data),
        rubric_json=json.dumps(rubric_data),
        duration_minutes=payload.durationMinutes or 20,
        closing=(
            payload.closing.strip()
            if payload.closing
            else "Thanks for your time. A recruiter will follow up with next steps."
        ),
        status="created",
    )

    db.add(session)
    await db.commit()
    await db.refresh(session)
    return to_dto(session)


@router.get("/{session_id}", status_code=status.HTTP_200_OK)
async def get_session_by_id(
    session_id: uuid.UUID, db: AsyncSession = Depends(get_session)
):
    """Retrieve details for a single interview session."""
    query = select(InterviewSession).where(InterviewSession.id == session_id)
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return to_dto(session)


@router.patch("/{session_id}", status_code=status.HTTP_200_OK)
async def update_session(
    session_id: uuid.UUID,
    payload: SessionUpdateSchema,
    db: AsyncSession = Depends(get_session),
):
    """Update a session's configuration (only allowed before the interview starts)."""
    query = select(InterviewSession).where(InterviewSession.id == session_id)
    result = await db.execute(query)
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )

    if session.status != "created":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot edit a session that has already started",
        )

    if payload.role is not None:
        session.role = payload.role.strip()
    if payload.intro is not None:
        session.intro = payload.intro.strip()
    if payload.candidateName is not None:
        session.candidate_name = (
            payload.candidateName.strip() if payload.candidateName else None
        )
    if payload.durationMinutes is not None:
        session.duration_minutes = payload.durationMinutes
    if payload.closing is not None:
        session.closing = (
            payload.closing.strip() if payload.closing else session.closing
        )

    if payload.questions is not None:
        questions_data = [
            {
                "text": q.text.strip(),
                "followUpHint": q.followUpHint.strip() if q.followUpHint else "",
                "maxFollowUps": q.maxFollowUps if q.maxFollowUps is not None else 2,
            }
            for q in payload.questions
        ]
        session.questions_json = json.dumps(questions_data)

    if payload.rubric is not None:
        rubric_data = [
            {
                "name": r.name.strip(),
                "description": r.description.strip() if r.description else "",
                "weight": r.weight if r.weight is not None else 1,
            }
            for r in payload.rubric
        ]
        session.rubric_json = json.dumps(rubric_data)

    await db.commit()
    await db.refresh(session)
    return to_dto(session)
