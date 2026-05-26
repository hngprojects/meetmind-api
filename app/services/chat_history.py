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
from app.schemas.transcript import TranscriptResponse, TranscriptTurnResponse


class ChatHistoryService:
    """Retrieve the full chat history for an interview session."""

    @staticmethod
    async def _assert_interview_belongs_to_user(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> Interview:
        result = await db.execute(
            select(Interview).where(
                Interview.id == interview_id,
                Interview.interviewer_id == user.id,
            )
        )
        interview = result.scalar_one_or_none()
        if not interview:
            raise APIError(
                "Interview not found",
                status_code=status.HTTP_404_NOT_FOUND,
                code="interview_not_found",
            )
        return interview

    @staticmethod
    def _format_elapsed_timestamp(first_timestamp: int, timestamp: int) -> str:
        elapsed = max(0, (timestamp or 0) - (first_timestamp or 0))
        minutes = elapsed // 60
        seconds = elapsed % 60
        return f"{minutes:02}:{seconds:02}"

    @staticmethod
    def _map_speaker(speaker: str) -> tuple[str, str]:
        mapping = {
            "ai": ("meet_mind", "Meet Mind"),
            "candidate": ("candidate", "Candidate"),
            "interviewer": ("interviewer", "Interviewer"),
        }
        return mapping.get(speaker, ("unknown", "Unknown"))

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
        await ChatHistoryService._assert_interview_belongs_to_user(
            interview_id, db, user
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

    @staticmethod
    async def get_transcript(
        interview_id: uuid.UUID,
        db: AsyncSession,
        # user: User,
    ) -> TranscriptResponse:
        # await ChatHistoryService._assert_interview_belongs_to_user(
        #     interview_id, db, user
        # )

        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
        transcript = transcript_result.scalar_one_or_none()

        if transcript is None:
            return TranscriptResponse(
                interview_id=interview_id,
                total_turns=0,
                turns=[],
            )

        turns_result = await db.execute(
            select(InterviewTranscriptTurn)
            .where(InterviewTranscriptTurn.transcript_id == transcript.id)
            .order_by(InterviewTranscriptTurn.sequence_no.asc())
        )
        turns = turns_result.scalars().all()

        first_timestamp = (
            turns[0].timestamp_sec if turns and turns[0].timestamp_sec else 0
        )
        transcript_turns = []
        for turn in turns:
            speaker, speaker_label = ChatHistoryService._map_speaker(turn.speaker)
            transcript_turns.append(
                TranscriptTurnResponse(
                    id=turn.id,
                    speaker=speaker,
                    speaker_label=speaker_label,
                    timestamp=ChatHistoryService._format_elapsed_timestamp(
                        first_timestamp, turn.timestamp_sec or 0
                    ),
                    content=turn.content,
                    is_typing=False,
                    is_active=False,
                    sequence_no=turn.sequence_no,
                )
            )

        return TranscriptResponse(
            interview_id=interview_id,
            total_turns=len(transcript_turns),
            turns=transcript_turns,
        )

    @staticmethod
    async def get_transcript_export(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> list[str]:
        await ChatHistoryService._assert_interview_belongs_to_user(
            interview_id, db, user
        )

        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
        transcript = transcript_result.scalar_one_or_none()

        lines: list[str] = []
        if transcript is not None:
            turns_result = await db.execute(
                select(InterviewTranscriptTurn)
                .where(InterviewTranscriptTurn.transcript_id == transcript.id)
                .order_by(InterviewTranscriptTurn.sequence_no.asc())
            )
            turns = turns_result.scalars().all()
            first_timestamp = (
                turns[0].timestamp_sec if turns and turns[0].timestamp_sec else 0
            )
            for turn in turns:
                _, speaker_label = ChatHistoryService._map_speaker(turn.speaker)
                timestamp = ChatHistoryService._format_elapsed_timestamp(
                    first_timestamp, turn.timestamp_sec or 0
                )
                lines.append(f"[{timestamp}] {speaker_label}: {turn.content}\n")

        if not lines:
            lines = [f"Transcript export for interview {interview_id}\n"]

        return lines
