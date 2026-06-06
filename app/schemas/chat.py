"""Pydantic schemas for interview chat history."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RespondRequest(BaseModel):
    content: str = Field(..., min_length=1)


class AskRequest(BaseModel):
    query: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    content: str = Field(..., min_length=1)


class ChatMessageResponse(BaseModel):
    """A single turn in the interview chat history."""

    id: UUID
    role: str
    content: str
    sent_at: datetime
    sequence_no: int

    model_config = {"from_attributes": True}


class ChatHistoryResponse(BaseModel):
    """Full chat history for a completed interview."""

    interview_id: UUID
    total_messages: int
    messages: list[ChatMessageResponse]


class ChatVoiceUploadResponse(BaseModel):
    """Response after uploading and transcribing an audio query."""

    role: str = "assistant"
    content: str
    transcription: str
    sent_at: datetime | None = None
    sequence_no: int


class ChatDocumentUploadResponse(BaseModel):
    """Response after uploading a document as a chat query."""

    role: str = "assistant"
    content: str
    document_text_preview: str
    sent_at: datetime | None = None
    sequence_no: int
