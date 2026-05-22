from __future__ import annotations
import uuid
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.interview_context_service import InterviewContextService
from app.services.chat_history import ChatHistoryService
from sdk.repositories import SDKRepository
from sdk.db import SDKSessionLocal
from app.models.user import User

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

        # 3. Call AI model (stub for now)
        ai_output = {
            "reply": "Tell me about a time you solved a complex technical challenge.",
            "highlights": ["Candidate shows strong coding background"],
            "red_flags": ["Candidate struggled with communication clarity"]
        }

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

        ai_output = {
            "summary": "Candidate demonstrated strong technical depth but weaker communication.",
            "keypoints": ["Strong coding background", "Weak presentation skills"],
            "decisions": ["Proceed to next round"],
            "action_items": [{"content": "Schedule follow-up interview", "assignee_name": "Recruiter"}]
        }

        return ai_output
    
    @staticmethod
    async def answer_query(
        db: AsyncSession,
        candidate_id: uuid.UUID,
        query: str,
    ) -> dict:
        """Answer a user query about a candidate or meeting."""
        
        # Build context from candidate docs + job description
        system_prompt = f"Answer the following query about candidate {candidate_id}: {query}"
        
        # Stub AI output for now
        ai_output = {
            "query": query,
            "answer": "Candidate demonstrated strong technical depth but weaker communication."
        }
        
        return ai_output


