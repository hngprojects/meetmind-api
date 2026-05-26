"""Bot service — uses existing SDKRepository for all persistence."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interview import Interview, InterviewSummary
from app.core.gemini import generate_text
from sdk.bot_manager import bot_manager
from sdk.models import SDKSession
from sdk.repositories import SDKRepository
from sdk.sdk import MeetMindSDK
from sdk.providers.google_meet_browser.events import (
    TranscriptEvent, StatusEvent, ErrorEvent, BotStatus,
)


class BotService:

    def __init__(self, async_db: AsyncSession, sync_db: Session | None = None):
        # async_db: used for reading app/interview models
        # sync_db: used by SDKRepository which is sync
        self.async_db = async_db
        self.sync_db = sync_db
        self.repo = SDKRepository(sync_db) if sync_db is not None else None
        self.sdk = MeetMindSDK(sync_db) if sync_db is not None else None

    async def join_meeting(
        self,
        interview_id: uuid.UUID,
        meeting_url: str,
        bot_name: str = "MeetMind",
        platform: str = "google_meet",
    ) -> dict:
        # Fetch interview context
        interview = await self._get_interview(interview_id)
        if not interview:
            raise ValueError(f"Interview {interview_id} not found")

        summary_result = await self.async_db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview_id
            )
        )
        summary = summary_result.scalar_one_or_none()

        # Build context string for the SDK session
        context = self._build_context(interview, summary)

        # Create SDKSession — choose the provider by platform
        if platform == "google_meet":
            sdk_session = self.sdk.create_google_meet_session(
                meeting_url=meeting_url,
                agent_name=bot_name,
                context=context,
            )
        elif platform == "zoom":
            sdk_session = self.sdk.create_zoom_session(
                meeting_url=meeting_url,
                agent_name=bot_name,
                context=context,
            )
        else:
            raise ValueError(f"Unsupported platform: {platform}")

        async def on_event(event):
            await self._handle_event(
                event=event,
                sdk_session=sdk_session,
                interview_id=interview_id,
            )

        # Start browser bot
        browser_session_id = await bot_manager.join(
            meeting_url=meeting_url,
            bot_name=bot_name,
            on_event=on_event,
            interview_id=str(interview_id),
            cleanup_callback=lambda: self.sync_db.close() if self.sync_db is not None else None,
        )

        # Store browser session id in SDKSession.provider_session_id
        self.repo.update_session_status(
            sdk_session,
            status="joining",
            provider_session_id=browser_session_id,
        )

        asyncio.create_task(
            self._speak_opening(
                browser_session_id=browser_session_id,
                sdk_session=sdk_session,
                interview_id=interview_id,
            )
        )

        return {
            "sdk_session_id": sdk_session.id,
            "browser_session_id": browser_session_id,
            "status": "joining",
        }

    async def leave_meeting(self, browser_session_id: str):
        await bot_manager.leave(browser_session_id)

    async def speak(self, browser_session_id: str, text: str):
        await bot_manager.speak(browser_session_id, text)

    async def _speak_opening(
        self,
        browser_session_id: str,
        sdk_session: SDKSession,
        interview_id: uuid.UUID,
    ):
        """Wait for bot to be in the meeting, then speak the first question."""
        import asyncio
        from app.models.interview import Candidate, InterviewSummary
        from app.services.ai_generation_service import AIGenerationService

        # Wait for bot to fully join (status becomes in_meeting)
        for _ in range(30):  # max 60 seconds
            await asyncio.sleep(3)
            session = bot_manager.get_session(browser_session_id)
            if session and session.status.value == "in_meeting":
                logging.info("Bot joined meeting sucessfully")
                break
        else:
            logging.warning("Bot never reached in_meeting status, skipping opening")
            return

        await asyncio.sleep(3)  # extra buffer after joining

        interview = await self._get_interview(interview_id)
        if not interview:
            return

        candidate_result = await self.async_db.execute(
            select(Candidate).where(Candidate.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        summary_result = await self.async_db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview_id
            )
        )
        summary = summary_result.scalar_one_or_none()

        if candidate and summary and summary.job_description:
            try:
                system_instruction = await AIGenerationService._build_question_context(
                    candidate_id=candidate.id,
                    job_description=summary.job_description,
                    scorecard=summary.scoring_rubric or "",
                    ai_tone=interview.ai_tone,
                    db=self.async_db,
                )
                opening = await generate_text(
                    system_instruction=system_instruction,
                    user_content=(
                        "This is the very start of the interview. "
                        "Greet the candidate warmly and ask your first interview question. "
                        "Keep it concise for a live audio call. Plain text only."
                    ),
                    temperature=0.7,
                    max_tokens=200,
                )
            except Exception:
                opening = (
                    f"Hello, welcome to your interview for the {interview.role_title or 'role'} position. "
                    "I'm MeetMind, your AI interviewer today. Could you start by telling me a bit about yourself?"
                )
        else:
            opening = (
                f"Hello, welcome to your interview for the {interview.role_title or 'role'} position. "
                "I'm MeetMind, your AI interviewer today. Could you start by telling me a bit about yourself?"
            )

        await bot_manager.speak(browser_session_id, opening)

    # ── Event handler ─────────────────────────────────────────────────────────

    async def _handle_event(
        self,
        event,
        sdk_session: SDKSession,
        interview_id: uuid.UUID,
    ):
        if isinstance(event, TranscriptEvent):
            # Use existing SDKRepository.add_transcript_turn
            if self.repo is not None:
                try:
                    self.repo.add_transcript_turn(
                        session=sdk_session,
                        source=event.source,           # "stt" | "caption" | "bot"
                        role=event.role,               # "human" | "agent"
                        speaker_name=event.speaker,
                        speaker_id=None,
                        content=event.text,
                        timestamp_ms=int(event.timestamp.timestamp() * 1000),
                        provider_stream_id=None,
                    )
                except Exception:
                    logging.exception(
                        "Failed to persist transcript turn for session %s",
                        sdk_session.id,
                    )
            try:
                await self._save_interview_transcript_turn(event, interview_id)
            except Exception:
                logging.exception(
                    "Failed to persist interview transcript turn for interview %s",
                    interview_id,
                )

            # Trigger AI response only for real human speech
            if event.source == "stt" and event.text.strip():
                await self._generate_ai_response(
                    sdk_session=sdk_session,
                    interview_id=interview_id,
                    candidate_text=event.text,
                )

        elif isinstance(event, StatusEvent):
            try:
                self.repo.update_session_status(
                    sdk_session,
                    status=event.status.value,
                )
            except Exception:
                logging.exception(
                    "Failed to update session status for session %s",
                    sdk_session.id,
                )

        elif isinstance(event, ErrorEvent):
            logging.error(
                f"[BotSession {event.session_id}] {event.error}\n{event.traceback}"
            )
            self.repo.update_session_status(sdk_session, status="error")

    async def _save_interview_transcript_turn(
        self,
        event: TranscriptEvent,
        interview_id: uuid.UUID,
    ):
        """Write a bot transcript event into InterviewTranscript/InterviewTranscriptTurn."""
        from app.models.interview import InterviewTranscript, InterviewTranscriptTurn
        from datetime import timezone

        # Get or create the InterviewTranscript record
        result = await self.async_db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
        transcript = result.scalar_one_or_none()

        if transcript is None:
            transcript = InterviewTranscript(
                interview_id=interview_id,
                status="processing",
            )
            self.async_db.add(transcript)
            await self.async_db.flush()

        # Get next sequence number
        from sqlalchemy import func
        seq_result = await self.async_db.execute(
            select(func.coalesce(func.max(InterviewTranscriptTurn.sequence_no), 0) + 1)
            .where(InterviewTranscriptTurn.transcript_id == transcript.id)
        )
        next_seq = seq_result.scalar_one()

        # Map bot event speaker to what ChatHistoryService expects
        # ChatHistoryService._map_speaker maps "ai" → MeetMind, "candidate" → Candidate
        if event.role == "agent":
            speaker = "ai"
        else:
            speaker = "candidate"

        turn = InterviewTranscriptTurn(
            transcript_id=transcript.id,
            speaker=speaker,
            speaker_name=event.speaker,
            content=event.text,
            sequence_no=next_seq,
            is_ai_question=(event.role == "agent"),
            timestamp_sec=int(event.timestamp.timestamp()),
        )
        self.async_db.add(turn)
        await self.async_db.commit()

    # ── AI response ───────────────────────────────────────────────────────────

    async def _generate_ai_response(
        self,
        sdk_session: SDKSession,
        interview_id: uuid.UUID,
        candidate_text: str,
    ):
        try:
            response = await self._build_ai_response(
                sdk_session=sdk_session,
                interview_id=interview_id,
                candidate_text=candidate_text,
            )
            if response:
                # Find the active browser session and speak
                for s in bot_manager.list_sessions():
                    if s["interview_id"] == str(interview_id):
                        await bot_manager.speak(s["session_id"], response)
                        break
        except Exception as e:
            import logging
            logging.error(f"AI response error: {e}")

    async def _build_ai_response(
    self,
    sdk_session: SDKSession,
    interview_id: uuid.UUID,
    candidate_text: str,
    ) -> str | None:
        from app.agent.interview import build_instructions, interview_from_api
        from app.models.interview import (
            Candidate, InterviewSummary,
            InterviewTranscript, InterviewTranscriptTurn,
        )

        interview = await self._get_interview(interview_id)
        if not interview:
            return None

        candidate_result = await self.async_db.execute(
            select(Candidate).where(Candidate.id == interview.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        summary_result = await self.async_db.execute(
            select(InterviewSummary).where(
                InterviewSummary.interview_id == interview_id
            )
        )
        summary = summary_result.scalar_one_or_none()

        # Build system instruction using the same builder as the LiveKit agent
        if summary and summary.job_description:
            try:
                from app.services.ai_generation import AIGenerationService
                system_instruction = await AIGenerationService._build_question_context(
                    candidate_id=candidate.id,
                    job_description=summary.job_description,
                    scorecard=summary.scoring_rubric or "",
                    ai_tone=interview.ai_tone,
                    db=self.async_db,
                )
            except Exception:
                logging.exception("RAG context failed, using basic system prompt")
                system_instruction = (
                    f"You are MeetMind, an AI interviewer for a {interview.role_title or 'role'} position. "
                    f"Tone: {interview.ai_tone or 'professional'}. "
                    "Ask one focused question at a time. Keep responses short for a live audio call. "
                    "Never give feedback on answers. Never reveal the rubric."
                )
        else:
            system_instruction = (
                f"You are MeetMind, an AI interviewer for a {interview.role_title or 'role'} position. "
                "Ask one focused question at a time. Keep responses short for a live audio call."
            )

        # Get full conversation history from InterviewTranscriptTurn
        transcript_result = await self.async_db.execute(
            select(InterviewTranscript).where(
                InterviewTranscript.interview_id == interview_id
            )
        )
        transcript = transcript_result.scalar_one_or_none()

        conversation_lines = []
        if transcript:
            turns_result = await self.async_db.execute(
                select(InterviewTranscriptTurn)
                .where(InterviewTranscriptTurn.transcript_id == transcript.id)
                .order_by(InterviewTranscriptTurn.sequence_no.asc())
            )
            turns = turns_result.scalars().all()
            conversation_lines = [
                f"Interviewer: {t.content}" if t.is_ai_question
                else f"Candidate: {t.content}"
                for t in turns
            ]

        conversation_text = (
            "\n".join(conversation_lines)
            if conversation_lines
            else "No conversation yet."
        )

        user_content = f"""# CONVERSATION SO FAR
{conversation_text}

# CANDIDATE JUST SAID
{candidate_text}

# TASK
Continue the interview naturally. Ask ONE follow-up question or move to the
next topic based on the candidate's answer and what has already been covered.
Keep it short and conversational — this is a live audio call.
Output the interviewer's response only. Plain text, no labels or markup.
"""

        try:
            return await generate_text(
                system_instruction=system_instruction,
                user_content=user_content,
                temperature=0.7,
                max_tokens=150,    # keep spoken responses short
            )
        except Exception:
            logging.exception("LLM call failed")
            return None


    async def _build_basic_ai_response(
        self,
        sdk_session: SDKSession,
        interview,
        candidate_text: str,
    ) -> str | None:
        """Fallback when RAG context is unavailable."""
        turns = self.repo.list_transcript(sdk_session.id) or []
        history = "\n".join(
            f"Interviewer: {t.content}" if t.role == "agent" else f"Candidate: {t.content}"
            for t in turns[-10:]
        ) or "No prior conversation."

        system_instruction = (
            f"You are MeetMind, an AI interviewer for a {interview.role_title or 'candidate'} role. "
            f"Tone: {interview.ai_tone or 'professional and concise'}. "
            "Ask one focused question at a time. Keep responses short for a live audio call."
        )
        user_content = (
            f"Conversation:\n{history}\n\n"
            f"Candidate just said: {candidate_text}\n\n"
            "Respond as the interviewer with a single concise question. Plain text only."
        )
        try:
            return await generate_text(
                system_instruction=system_instruction,
                user_content=user_content,
                temperature=0.7,
                max_tokens=200,
            )
        except Exception:
            return None
    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_context(
        self, interview: Interview, summary: InterviewSummary | None
    ) -> str:
        parts: list[str] = []
        if interview.role_title:
            parts.append(f"Role: {interview.role_title}")
        if interview.ai_tone:
            parts.append(f"Tone: {interview.ai_tone}")
        if summary:
            if summary.job_description:
                parts.append(f"JobDescription: {summary.job_description}")
            if summary.scoring_rubric:
                parts.append(f"Scorecard: {summary.scoring_rubric}")
        # Keep context reasonably short for injected SDK sessions
        return " \n ".join(parts)[:4000]

    async def _get_interview(self, interview_id: uuid.UUID) -> Interview | None:
        result = await self.async_db.execute(select(Interview).where(Interview.id == interview_id))
        return result.scalar_one_or_none()