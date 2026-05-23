"""Bot service — uses existing SDKRepository for all persistence."""

from __future__ import annotations

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

        return {
            "sdk_session_id": sdk_session.id,
            "browser_session_id": browser_session_id,
            "status": "joining",
        }

    async def leave_meeting(self, browser_session_id: str):
        await bot_manager.leave(browser_session_id)

    async def speak(self, browser_session_id: str, text: str):
        await bot_manager.speak(browser_session_id, text)

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

            # Trigger AI response only for real human speech
            if event.source == "stt" and event.text.strip():
                await self._generate_ai_response(
                    sdk_session=sdk_session,
                    interview_id=interview_id,
                    candidate_text=event.text,
                )

        elif isinstance(event, StatusEvent):
            self.repo.update_session_status(
                sdk_session,
                status=event.status.value,
            )

        elif isinstance(event, ErrorEvent):
            import logging
            logging.error(
                f"[BotSession {event.session_id}] {event.error}\n{event.traceback}"
            )
            self.repo.update_session_status(sdk_session, status="error")

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
        interview = await self._get_interview(interview_id)
        if not interview:
            return None

        # Pull recent transcript turns from SDKRepository
        turns = self.repo.list_transcript(sdk_session.id) or []
        history_lines = [
            f"Interviewer: {t.content}" if t.role == "agent" else f"Candidate: {t.content}"
            for t in turns[-10:]
        ]
        history = "\n".join(history_lines) if history_lines else "No prior conversation."

        system_instruction = (
            f"You are MeetMind, an AI interviewer for a {interview.role_title or 'candidate'} role. "
            f"Tone: {interview.ai_tone or 'professional and concise'}. "
            "You are speaking in a live audio interview. Ask one focused question at a time and keep responses short."
        )

        user_content = (
            f"Conversation:\n{history}\n\nCandidate just said: {candidate_text}\n\n"
            "Task: Respond as the interviewer with a single concise question or follow-up suitable for a live call. "
            "Answer using plain text only (no JSON or markup)."
        )

        try:
            reply = await generate_text(
                system_instruction=system_instruction,
                user_content=user_content,
                temperature=0.7,
                max_tokens=200,
            )
            return reply
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