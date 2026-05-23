"""Pydantic schemas for interview transcript endpoints."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class TranscriptTurnResponse(BaseModel):
    """A single turn in the interview transcript."""

    id: UUID
    speaker: str
    speaker_label: str
    timestamp: str
    content: str
    is_typing: bool
    is_active: bool
    sequence_no: int

    model_config = {"from_attributes": True}


class TranscriptResponse(BaseModel):
    """Full interview transcript response."""

    interview_id: UUID
    total_turns: int
    turns: list[TranscriptTurnResponse]
