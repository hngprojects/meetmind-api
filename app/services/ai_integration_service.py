from __future__ import annotations
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.interview_context_service import InterviewContextService
from app.services.chat_history import ChatHistoryService
from sdk.repositories import SDKRepository
from sdk.db import SDKSessionLocal
from app.models.user import User
from app.core.ai import gemini_model

class AIIntegrationService:
    """Central AI integration layer for MeetMind."""

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

        response = gemini_model.generate_content(prompt)

        try:
            ai_output = response.json
        except Exception:
            ai_output = {"reply": response.text, "highlights": [], "red_flags": []}

        # 4. Persist reply into transcript via SDK session (sync)
        with SDKSessionLocal() as sdk_db:
            sdk_repo = SDKRepository(sdk_db)
            session = sdk_repo.get_session(session_id)
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
        candidate_id: uuid.UUID,
        job_description: str,
        scoring_rubric: str,
        transcript_text: str,
    ) -> dict:
        """Generate a post-interview summary and scorecard."""

        system_prompt = await InterviewContextService.build_session_context(
            candidate_id=candidate_id,
            job_description=job_description,
            scorecard=scoring_rubric,
            db=db,
        )

        prompt = f"""
{system_prompt}

Transcript:
{transcript_text}

Summarize the candidate’s performance.
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

        response = gemini_model.generate_content(prompt)

        try:
            ai_output = response.json
        except Exception:
            ai_output = {
                "summary": response.text,
                "keypoints": [],
                "decisions": [],
                "action_items": [],
            }

        return ai_output
    
    @staticmethod
    async def answer_query(
        db: AsyncSession,
        candidate_id: uuid.UUID,
        query: str,
    ) -> dict:
        """Answer a user query about a candidate or meeting."""
        
        prompt = f"""
Candidate ID: {candidate_id}
Question: {query}

Answer based on interview context.
Return ONLY valid JSON with this structure:

{{
  "query": "string",
  "answer": "string"
}}
"""

        response = gemini_model.generate_content(prompt)

        try:
            ai_output = response.json
        except Exception:
            ai_output = {"query": query, "answer": response.text}
        
        return ai_output


