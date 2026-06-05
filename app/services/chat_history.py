import json
import logging
import uuid

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.responses import APIError
from app.models.interview import (
    Interview,
    InterviewSession,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.user import User
from app.schemas.chat import ChatHistoryResponse, ChatMessageResponse
from app.schemas.transcript import TranscriptResponse, TranscriptTurnResponse

logger = logging.getLogger(__name__)


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
        # Safely compute elapsed seconds and prevent negative values
        elapsed = max(0, (timestamp or 0) - (first_timestamp or 0))
        # Extract hours, minutes, and seconds
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        # Format with 2-digit zero-padding for all blocks
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    @staticmethod
    def _map_speaker(speaker: str) -> tuple[str, str]:
        mapping = {
            "ai": ("meet_mind", "Meet Mind"),
            "candidate": ("candidate", "Candidate"),
            "interviewer": ("interviewer", "Interviewer"),
        }
        return mapping.get(speaker, ("unknown", "Unknown"))

    @staticmethod
    async def _get_fallback_turns_from_session(
        interview: Interview,
        db: AsyncSession,
    ) -> list[dict]:
        if not interview.session_id:
            return []
        session = await db.get(InterviewSession, interview.session_id)
        if not session or not session.transcript_json:
            return []
        try:
            fallback_turns = json.loads(session.transcript_json)
            if isinstance(fallback_turns, list):
                return fallback_turns
        except Exception as e:
            logger.exception(
                "Failed to parse fallback transcript JSON from session %s: %s",
                interview.session_id,
                e,
            )
        return []

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
        interview = await ChatHistoryService._assert_interview_belongs_to_user(
            interview_id, db, user
        )

        # 2. Fetch the associated transcript record.
        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
        transcript = transcript_result.scalar_one_or_none()

        turns = []
        if transcript is not None:
            # 3. Fetch all turns ordered by sequence_no ascending.
            turns_result = await db.execute(
                select(InterviewTranscriptTurn)
                .where(InterviewTranscriptTurn.transcript_id == transcript.id)
                .order_by(InterviewTranscriptTurn.sequence_no.asc())
            )
            turns = turns_result.scalars().all()

        messages = []
        if turns:
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
        else:
            # Fallback to session JSON
            fallback_turns = await ChatHistoryService._get_fallback_turns_from_session(
                interview,
                db,
            )
            from datetime import datetime, timedelta, timezone

            base_time = interview.started_at or interview.created_at
            if base_time is None:
                base_time = datetime.now(timezone.utc)
            else:
                if base_time.tzinfo is None:
                    base_time = base_time.replace(tzinfo=timezone.utc)

            messages = []
            for idx, turn_data in enumerate(fallback_turns):
                seq_no = turn_data.get("sequence_no") or (idx + 1)
                messages.append(
                    ChatMessageResponse(
                        id=uuid.uuid5(
                            uuid.NAMESPACE_DNS,
                            f"meetmind-turn-{interview_id}-{seq_no}",
                        ),
                        role=turn_data.get("speaker", "unknown"),
                        content=turn_data.get("content") or turn_data.get("text") or "",
                        sent_at=base_time
                        + timedelta(
                            seconds=turn_data.get("timestamp_sec") or 0,
                        ),
                        sequence_no=seq_no,
                    )
                )

        return ChatHistoryResponse(
            interview_id=interview_id,
            total_messages=len(messages),
            messages=messages,
        )

    @staticmethod
    async def get_transcript(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
        *,
        live: bool = False,
        after_sequence_no: int | None = None,
    ) -> TranscriptResponse:
        interview = await ChatHistoryService._assert_interview_belongs_to_user(
            interview_id, db, user
        )
        is_live = interview.status == "in_progress"

        # --- Derive transcript status ---
        if is_live:
            response_status = "transcribing"
        elif interview.status in ("draft", "scheduled"):
            response_status = "connecting" if live else "idle"
        elif interview.status == "cancelled":
            response_status = "failed"
        elif interview.status == "needs_attention":
            response_status = "interrupted"
        else:
            response_status = "completed"

        # --- Populate error / message / partial_saved envelope ---
        error: str | None = None
        message: str | None = None
        partial_saved: bool | None = None

        if response_status == "idle":
            message = (
                "Live transcription will appear here when an interview begins."
            )
        elif response_status == "connecting":
            message = "Connecting to live transcript stream…"
        elif response_status == "interrupted":
            error = "feed_lost"
            message = "Live transcript stream was interrupted."
            partial_saved = True
        elif response_status == "failed":
            error = "interview_cancelled"
            message = "Interview was cancelled."
            partial_saved = True

        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
        transcript = transcript_result.scalar_one_or_none()

        turns = []
        if transcript is not None:
            query = (
                select(InterviewTranscriptTurn)
                .where(InterviewTranscriptTurn.transcript_id == transcript.id)
                .order_by(InterviewTranscriptTurn.sequence_no.asc())
            )
            if after_sequence_no is not None:
                query = query.where(
                    InterviewTranscriptTurn.sequence_no > after_sequence_no
                )
            turns_result = await db.execute(query)
            turns = turns_result.scalars().all()

        transcript_turns = []
        if turns:
            first_timestamp = (
                turns[0].timestamp_sec if turns and turns[0].timestamp_sec else 0
            )
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
                        text=turn.content,
                        speaker_type=speaker,
                        is_typing=False,
                        is_active=False,
                        sequence_no=turn.sequence_no,
                    )
                )
        else:
            fallback_turns = await ChatHistoryService._get_fallback_turns_from_session(
                interview,
                db,
            )
            first_timestamp = (
                fallback_turns[0].get("timestamp_sec")
                if fallback_turns and fallback_turns[0].get("timestamp_sec")
                else 0
            )
            for idx, turn_data in enumerate(fallback_turns):
                speaker = turn_data.get("speaker", "unknown")
                content = turn_data.get("content") or turn_data.get("text") or ""
                timestamp_sec = turn_data.get("timestamp_sec") or 0
                seq_no = turn_data.get("sequence_no") or (idx + 1)

                # Skip turns the client already has when using cursor
                if after_sequence_no is not None and seq_no <= after_sequence_no:
                    continue

                speaker_role, speaker_label = ChatHistoryService._map_speaker(speaker)
                transcript_turns.append(
                    TranscriptTurnResponse(
                        id=uuid.uuid5(
                            uuid.NAMESPACE_DNS,
                            f"meetmind-turn-{interview_id}-{seq_no}",
                        ),
                        speaker=speaker_role,
                        speaker_label=speaker_label,
                        timestamp=ChatHistoryService._format_elapsed_timestamp(
                            first_timestamp, timestamp_sec
                        ),
                        content=content,
                        text=content,
                        speaker_type=speaker_role,
                        is_typing=False,
                        is_active=False,
                        sequence_no=seq_no,
                    )
                )

        return TranscriptResponse(
            interview_id=interview_id,
            total_turns=len(transcript_turns),
            turns=transcript_turns,
            is_live=is_live,
            status=response_status,
            messages=transcript_turns,
            error=error,
            message=message,
            partial_saved=partial_saved,
        )

    @staticmethod
    async def get_transcript_export(
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> list[str]:
        interview = await ChatHistoryService._assert_interview_belongs_to_user(
            interview_id, db, user
        )

        transcript_result = await db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
        transcript = transcript_result.scalar_one_or_none()

        turns = []
        if transcript is not None:
            turns_result = await db.execute(
                select(InterviewTranscriptTurn)
                .where(InterviewTranscriptTurn.transcript_id == transcript.id)
                .order_by(InterviewTranscriptTurn.sequence_no.asc())
            )
            turns = turns_result.scalars().all()

        lines: list[str] = []
        if turns:
            first_timestamp = (
                turns[0].timestamp_sec if turns and turns[0].timestamp_sec else 0
            )
            for turn in turns:
                _, speaker_label = ChatHistoryService._map_speaker(turn.speaker)
                timestamp = ChatHistoryService._format_elapsed_timestamp(
                    first_timestamp, turn.timestamp_sec or 0
                )
                lines.append(f"[{timestamp}] {speaker_label}: {turn.content}\n")
        else:
            fallback_turns = await ChatHistoryService._get_fallback_turns_from_session(
                interview,
                db,
            )
            if fallback_turns:
                first_timestamp = (
                    fallback_turns[0].get("timestamp_sec")
                    if fallback_turns and fallback_turns[0].get("timestamp_sec")
                    else 0
                )
                for idx, turn_data in enumerate(fallback_turns):
                    speaker = turn_data.get("speaker", "unknown")
                    content = turn_data.get("content") or turn_data.get("text") or ""
                    timestamp_sec = turn_data.get("timestamp_sec") or 0

                    _, speaker_label = ChatHistoryService._map_speaker(speaker)
                    timestamp = ChatHistoryService._format_elapsed_timestamp(
                        first_timestamp, timestamp_sec
                    )
                    lines.append(f"[{timestamp}] {speaker_label}: {content}\n")

        if not lines:
            lines = [f"Transcript export for interview {interview_id}\n"]

        return lines
