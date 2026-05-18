"""Interview chat history service."""

from __future__ import annotations

import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.interview import Interview, InterviewTranscript, InterviewTranscriptTurn
from app.models.user import User
from app.schemas.chat import ChatHistoryResponse, ChatMessageResponse


class ChatHistoryService:
    """Retrieve the full chat history for an interview session."""

    @staticmethod
    async def get_chat_history(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> ChatHistoryResponse:
        """Return all transcript turns for an interview, ordered by sequence_no.

        Scopes the lookup to the requesting user's own interviews — matching
        the same guard used in InterviewService.get_interview.

        Args:
            interview_id: UUID of the interview to fetch history for.
            db: Active async database session.
            user: The authenticated user.

        Returns:
            A populated :class:`ChatHistoryResponse`.

        Raises:
            APIError: 404 if the interview does not exist or does not belong
                to the requesting user. Same message in both cases — no leakage.
        """
        # 1. Verify interview exists and belongs to the requesting user.
        interview_result = await db.execute(
            select(Interview).where(
                Interview.id == interview_id,
                Interview.interviewer_id == user.id,
            )
        )
        interview = interview_result.scalar_one_or_none()

        if not interview:
            raise APIError(
                "Interview not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="interview_not_found",
            )

        # 2. Fetch the associated transcript record.
        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
        transcript = transcript_result.scalar_one_or_none()

        # Interview exists but no transcript yet — return empty history, not 404.
        if transcript is None:
            return ChatHistoryResponse(
                interview_id=interview_id,
                total_messages=0,
                messages=[],
            )

        # 3. Fetch all turns ordered by sequence_no ascending.
        turns_result = await db.execute(
            select(InterviewTranscriptTurn)
            .where(InterviewTranscriptTurn.transcript_id == transcript.id)
            .order_by(InterviewTranscriptTurn.sequence_no.asc())
        )
        turns = turns_result.scalars().all()

        messages = [
            ChatMessageResponse(
                id=turn.id,
                role=turn.speaker,
                content=turn.content,
                sent_at=turn.created_at,
                sequence_no=turn.sequence_no,
            )
            for turn in turns
        ]

        return ChatHistoryResponse(
            interview_id=interview_id,
            total_messages=len(messages),
            messages=messages,
        )
