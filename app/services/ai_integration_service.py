from __future__ import annotations

import json
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai import generate_with_gemini
from app.models.user import User
from app.services.chat_history import ChatHistoryService
from app.services.interview_context_service import InterviewContextService
from sdk.db import SDKSessionLocal
from sdk.repositories import SDKRepository


class AIIntegrationService:
    """Central AI integration layer for MeetMind."""

    @staticmethod
    def _extract_ai_output(response, fallback_keys: dict) -> dict:
        """
        Extracts and normalizes AI output into a dict with stable keys.
        Ensures we always return the expected shape, even if parsing fails.
        """
        try:
            candidate_text = response.candidates[0].content.parts[0].text
        except Exception:
            candidate_text = str(getattr(response, "text", response))

        # Remove Markdown code fences if present
        clean_text = re.sub(r"^```json\n|\n```$", "", candidate_text.strip())

        # Try to parse JSON
        try:
            parsed = json.loads(clean_text)
            return {k: parsed.get(k, v) for k, v in fallback_keys.items()}
        except Exception:
            # Fallback: return text in the "reply"/primary field, defaults for others
            return {
                k: (clean_text if k in ("reply", "summary", "answer") else v)
                for k, v in fallback_keys.items()
            }

    @staticmethod
    async def generate_reply(
        db: AsyncSession,
        interview_id: uuid.UUID,
        session_id: str,
        candidate_id: uuid.UUID,
        job_description: str,
        scoring_rubric: str,
        transcript_text: str,
        user: User,
    ) -> dict:
        """Generate an AI reply during interview and persist it."""

        # 1. Build context from candidate docs + job description
        system_prompt = await InterviewContextService.build_session_context(
            candidate_id=candidate_id,
            job_description=job_description,
            scorecard=scoring_rubric,
            db=db,
        )

        # 2. Include chat history (scoped to interview + user)
        history = await ChatHistoryService.get_chat_history(interview_id, db, user)

        # 3. Call Gemini model with structured JSON request
        prompt = f"""
{system_prompt}

Conversation history:
{history}

Candidate said: {transcript_text}

Generate the next interviewer reply.
Return ONLY valid JSON with this structure:

{{
  "reply": "string",
  "highlights": ["string"],
  "red_flags": ["string"]
}}
"""

        response = await generate_with_gemini(prompt)
        ai_output = AIIntegrationService._extract_ai_output(
            response,
            fallback_keys={"reply": "", "highlights": [], "red_flags": []},
        )

        # 4. Persist reply into transcript via SDK session (sync)
        with SDKSessionLocal() as sdk_db:
            sdk_repo = SDKRepository(sdk_db)
            session = sdk_repo.get_session(session_id)
            if session is not None:
                sdk_repo.add_transcript_turn(
                    session=session,
                    source="ai",
                    role="ai",
                    speaker_name="MeetMind",
                    speaker_id=None,
                    content=ai_output["reply"],
                    timestamp_ms=None,
                    provider_stream_id=None,
                    trigger_reason="ai_response",
                )

        return ai_output

    @staticmethod
    async def generate_summary(
        db: AsyncSession,
        interview_id: uuid.UUID,
        candidate_id: uuid.UUID,
        job_description: str,
        scoring_rubric: str,
        transcript_text: str,
        user: User,
    ) -> dict:
        """Generate a post-interview summary and scorecard."""

        system_prompt = await InterviewContextService.build_session_context(
            candidate_id=candidate_id,
            job_description=job_description,
            scorecard=scoring_rubric,
            db=db,
        )

        history = await ChatHistoryService.get_chat_history(interview_id, db, user)

        prompt = f"""
{system_prompt}

Conversation history:
{history}

Transcript:
{transcript_text}

Summarize the candidate’s performance. 
Do not include dialogue. 
Do not ask questions. 
Return ONLY valid JSON with this structure:

{{
  "summary": "string",
  "keypoints": ["string"],
  "decisions": ["string"],
  "action_items": [
    {{"content": "string", "assignee_name": "string"}}
  ]
}}
"""

        response = await generate_with_gemini(prompt)
        return AIIntegrationService._extract_ai_output(
            response,
            fallback_keys={
                "summary": "",
                "keypoints": [],
                "decisions": [],
                "action_items": [],
            },
        )

    @staticmethod
    async def answer_query(
        db: AsyncSession,
        interview_id: uuid.UUID,
        candidate_id: uuid.UUID,
        query: str,
        user: User,
        transcript_text: str,
    ) -> dict:
        """Answer a user query about a candidate or meeting."""

        system_prompt = await InterviewContextService.build_session_context(
            candidate_id=candidate_id,
            job_description="",  # optional if not needed
            scorecard="",  # optional if not needed
            db=db,
        )

        history = await ChatHistoryService.get_chat_history(interview_id, db, user)

        prompt = f"""
{system_prompt}

Conversation history:
{history}

Transcript:
{transcript_text}

You are generating a factual answer to a user query about the candidate.
Do not include dialogue.
Do not ask questions.
Do not roleplay as the candidate.
Return ONLY valid JSON with this structure:

{{
  "query": "{query}",
  "answer": "string"
}}

Where "answer" is a concise factual summary 
of the candidate's strengths, weaknesses, 
or other requested information, based on 
the transcript and context.
"""

        response = await generate_with_gemini(prompt)
        return AIIntegrationService._extract_ai_output(
            response, fallback_keys={"query": query, "answer": ""}
        )
