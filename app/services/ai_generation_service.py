"""AI generation service for interview questions, assessments, and Q&A."""
# ruff: noqa: E501

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.gemini import generate_structured_output, generate_text
from app.core.responses import APIError
from app.models.interview import (
    Candidate,
    Interview,
    InterviewSummary,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.user import User
from app.schemas.assessment import AssessmentOutput
from app.services.chat_history import ChatHistoryService
from app.services.interview_context_service import InterviewContextService

logger = logging.getLogger(__name__)


class AIGenerationService:
    """Generate interview questions, assessments, and answer queries."""

    # ── Prompt builders ──────────────────────────────────────────────────────

    @classmethod
    async def _build_question_context(
        cls,
        candidate_id: uuid.UUID,
        job_description: str,
        scorecard: str,
        ai_tone: str | None,
        db: AsyncSession,
    ) -> str:
        """Build the system instruction for next-question generation.

        Retrieves relevant resume/document chunks via
        :meth:`InterviewContextService.retrieve_relevant_chunks`. If no chunks
        are found (empty list), the ``# CANDIDATE CONTEXT`` section is left
        blank — the LLM proceeds with the job description and scorecard alone.
        """
        retrieved = await InterviewContextService.retrieve_relevant_chunks(
            candidate_id=candidate_id,
            query=(
                f"Candidate experience, skills, and background relevant "
                f"to: {job_description}"
            ),
            db=db,
        )
        resume_context = "\n---\n".join(retrieved)

        tone_map = {
            "professional": "Maintain a professional and formal tone.",
            "friendly": "Keep the tone warm and approachable.",
            "casual": "Use a relaxed and conversational tone.",
        }
        tone_instruction = (
            tone_map.get(ai_tone, "Keep the tone natural and conversational.")
            if ai_tone
            else "Keep the tone natural and conversational."
        )

        return f"""
                You are MeetMind, an expert Technical Recruiter conducting an interview.
                You are speaking to the candidate via a live audio call. Keep your responses
                conversational, concise, and natural. Do not speak in bullet points.

                {tone_instruction}

                # JOB DESCRIPTION
                {job_description}

                # EVALUATION SCORECARD
                {scorecard}

                # CANDIDATE CONTEXT (From Uploaded Resume/Docs)
                {resume_context}

                # RULES
                - Ask one question at a time.
                - Do not repeat questions you have already asked.
                - Base your questions on the candidate's background and the scorecard criteria.
                - If the candidate has not addressed a key skill, probe it with a follow-up.
                - Keep questions concise for a live audio call.
                """.strip()

    @classmethod
    async def _build_assessment_context(
        cls,
        candidate_id: uuid.UUID,
        job_description: str,
        scorecard: str,
        db: AsyncSession,
    ) -> str:
        """Build the system instruction for post-session assessment generation.

        Retrieves relevant resume/document chunks via
        :meth:`InterviewContextService.retrieve_relevant_chunks`. If no chunks
        are found (empty list), the ``# CANDIDATE CONTEXT`` section is left
        blank — the LLM proceeds with the job description, scorecard, and
        transcript alone.
        """
        retrieved = await InterviewContextService.retrieve_relevant_chunks(
            candidate_id=candidate_id,
            query=(
                f"Candidate experience, skills, and background relevant "
                f"to: {job_description}"
            ),
            db=db,
        )
        resume_context = "\n---\n".join(retrieved)

        return f"""
                You are MeetMind, an expert Technical Recruiter evaluating a candidate after an interview.

                # JOB DESCRIPTION
                {job_description}

                # EVALUATION SCORECARD
                {scorecard}

                # CANDIDATE CONTEXT (From Uploaded Resume/Docs)
                {resume_context}

                # INSTRUCTIONS
                Based on the full interview transcript below, provide a detailed assessment
                of the candidate. Evaluate them against each scorecard criterion. Highlight
                strengths, weaknesses, and any red flags. Conclude with an overall recommendation.
                """.strip()

    # ── Core generation methods ──────────────────────────────────────────────

    @classmethod
    async def generate_next_question(
        cls,
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> str:
        """Generate the next interview question using context and conversation history.

        Args:
            interview_id: UUID of the interview session.
            db: Active async database session.
            user: The authenticated user (must be the interviewer).

        Returns:
            The generated question text.

        Raises:
            APIError: 404 if the interview is not found or does not belong to the user.
            APIError: 400 if the interview context is incomplete.
        """
        # 1. Fetch interview with auth check
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
                status_code=404,
                code="interview_not_found",
            )

        # 2. Fetch candidate and summary
        candidate = (
            await db.execute(
                select(Candidate).where(Candidate.id == interview.candidate_id)
            )
        ).scalar_one_or_none()

        summary = (
            await db.execute(
                select(InterviewSummary).where(
                    InterviewSummary.interview_id == interview_id
                )
            )
        ).scalar_one_or_none()

        if not candidate or not summary or not summary.job_description:
            raise APIError(
                "Interview context is incomplete",
                status_code=400,
                code="incomplete_context",
            )

        # 3. Build system instruction with RAG context
        system_instruction = await cls._build_question_context(
            candidate_id=candidate.id,
            job_description=summary.job_description,
            scorecard=summary.scoring_rubric or "",
            ai_tone=interview.ai_tone,
            db=db,
        )

        # 4. Get conversation history
        history = await ChatHistoryService.get_chat_history(interview_id, db, user)

        # 5. Format conversation turns
        conversation_lines = []
        for msg in history.messages:
            prefix = "Interviewer" if msg.role == "ai" else "Candidate"
            conversation_lines.append(f"{prefix}: {msg.content}")

        conversation_text = (
            "\n".join(conversation_lines)
            if conversation_lines
            else "No conversation yet — this is the beginning of the interview."
        )

        user_content = f"""# CONVERSATION SO FAR
            {conversation_text}

            # TASK
            Based on the conversation so far and the scorecard criteria, generate the next
            interview question. Keep it concise and conversational for a live audio call.
            Only output the question, nothing else.
            """

        # 6. Call LLM
        question = await generate_text(
            system_instruction=system_instruction,
            user_content=user_content,
            temperature=0.7,
            max_tokens=500,
        )

        # 7. Ensure a transcript record exists
        transcript = (
            await db.execute(
                select(InterviewTranscript).where(
                    InterviewTranscript.interview_id == interview_id
                )
            )
        ).scalar_one_or_none()

        if transcript is None:
            transcript = InterviewTranscript(
                interview_id=interview_id,
                status="processing",
            )
            db.add(transcript)
            await db.flush()

        # 8. Determine next sequence number
        last_seq = (
            await db.execute(
                select(InterviewTranscriptTurn.sequence_no)
                .where(InterviewTranscriptTurn.transcript_id == transcript.id)
                .order_by(InterviewTranscriptTurn.sequence_no.desc())
                .limit(1)
            )
        ).scalar_one_or_none() or 0

        # 9. Persist the question as a transcript turn
        turn = InterviewTranscriptTurn(
            transcript_id=transcript.id,
            speaker="ai",
            speaker_name="MeetMind",
            content=question,
            sequence_no=last_seq + 1,
            is_ai_question=True,
            timestamp_sec=int(datetime.now(timezone.utc).timestamp()),
        )
        db.add(turn)
        await db.commit()

        return question

    @classmethod
    async def generate_assessment(
        cls,
        interview_id: uuid.UUID,
        db: AsyncSession,
    ) -> None:
        """Generate a post-interview assessment and persist it on the summary.

        Designed to run as a background task — no auth check, no return value.

        Behavior on missing data:
        - If the interview, candidate, summary, or job description is not found,
          sets ``summary.status`` to ``"failed"`` and returns early.
        - If no transcript or no transcript turns exist,
          sets ``summary.status`` to ``"failed"`` and returns early.
        - If the LLM call or any other step raises, the summary is marked
          ``"failed"``.

        Args:
            interview_id: UUID of the completed interview.
            db: Active async database session.
        """
        try:
            # 1. Fetch interview, candidate, summary
            interview = (
                await db.execute(select(Interview).where(Interview.id == interview_id))
            ).scalar_one_or_none()

            candidate = (
                await db.execute(
                    select(Candidate).where(Candidate.id == interview.candidate_id)
                )
            ).scalar_one_or_none()

            summary = (
                await db.execute(
                    select(InterviewSummary).where(
                        InterviewSummary.interview_id == interview_id
                    )
                )
            ).scalar_one_or_none()

            if not candidate or not summary or not summary.job_description:
                if summary:
                    summary.status = "failed"
                    await db.commit()
                return

            # 2. Mark as generating
            summary.status = "generating"
            await db.commit()

            # 3. Build system instruction
            system_instruction = await cls._build_assessment_context(
                candidate_id=candidate.id,
                job_description=summary.job_description,
                scorecard=summary.scoring_rubric or "",
                db=db,
            )

            # 4. Fetch full transcript directly (no auth — background task)
            transcript = (
                await db.execute(
                    select(InterviewTranscript).where(
                        InterviewTranscript.interview_id == interview_id
                    )
                )
            ).scalar_one_or_none()

            if not transcript:
                summary.status = "failed"
                await db.commit()
                return

            turns = (
                (
                    await db.execute(
                        select(InterviewTranscriptTurn)
                        .where(InterviewTranscriptTurn.transcript_id == transcript.id)
                        .order_by(InterviewTranscriptTurn.sequence_no.asc())
                    )
                )
                .scalars()
                .all()
            )

            if not turns:
                summary.status = "failed"
                await db.commit()
                return

            lines = []
            for t in turns:
                speaker = "Interviewer" if t.is_ai_question else "Candidate"
                lines.append(f"{speaker}: {t.content}")
            turns_text = "\n".join(lines)
            user_content = f"""# FULL INTERVIEW TRANSCRIPT
                        {turns_text}

                        # TASK
                        Evaluate the candidate based on the transcript and scorecard above.
                        Cover each criterion, note strengths and weaknesses, flag any red flags,
                        and provide an overall recommendation.
                        """

            result = await generate_structured_output(
                system_instruction=system_instruction,
                user_content=user_content,
                output_schema=AssessmentOutput,
                temperature=0.3,
                max_tokens=2000,
            )

            summary.ai_assessment = json.dumps(result)
            summary.status = "completed"
            summary.generated_at = datetime.now(timezone.utc)
            await db.commit()

        except Exception:
            # 7. Mark as failed
            try:
                if summary:
                    summary.status = "failed"
                    await db.commit()
            except Exception:
                await db.rollback()

    @classmethod
    async def answer_query(
        cls,
        interview_id: uuid.UUID,
        query: str,
        user: User,
        db: AsyncSession,
    ) -> str:
        """Answer a natural language query about an interview session.

        Builds a prompt from the interview's job description, scorecard rubric,
        AI assessment, and transcript. Any missing data (no summary, no
        assessment, no transcript) is substituted with empty strings or
        ``"No transcript available."`` — the LLM is instructed to say so if
        the answer is not in the provided context.

        Args:
            interview_id: UUID of the interview to query against.
            query: The user's natural language question.
            user: The authenticated user (must be the interviewer).
            db: Active async database session.

        Returns:
            The generated answer text.

        Raises:
            APIError: 404 if the interview is not found or does not belong to the user.
        """
        # 1. Fetch interview with auth check
        interview = (
            await db.execute(
                select(Interview).where(
                    Interview.id == interview_id,
                    Interview.interviewer_id == user.id,
                )
            )
        ).scalar_one_or_none()

        if not interview:
            raise APIError(
                "Interview not found",
                status_code=404,
                code="interview_not_found",
            )

        # 2. Fetch summary and candidate
        summary = (
            await db.execute(
                select(InterviewSummary).where(
                    InterviewSummary.interview_id == interview_id
                )
            )
        ).scalar_one_or_none()

        _ = (
            await db.execute(
                select(Candidate).where(Candidate.id == interview.candidate_id)
            )
        ).scalar_one_or_none()

        jd = summary.job_description if summary else ""
        rubric = summary.scoring_rubric if summary else ""
        assessment = summary.ai_assessment if summary else ""

        # 3. Fetch transcript
        transcript = (
            await db.execute(
                select(InterviewTranscript).where(
                    InterviewTranscript.interview_id == interview_id
                )
            )
        ).scalar_one_or_none()

        transcript_text = "No transcript available."
        if transcript:
            turns = (
                (
                    await db.execute(
                        select(InterviewTranscriptTurn)
                        .where(InterviewTranscriptTurn.transcript_id == transcript.id)
                        .order_by(InterviewTranscriptTurn.sequence_no.asc())
                    )
                )
                .scalars()
                .all()
            )

            if turns:
                lines = []
                for t in turns:
                    speaker = "Interviewer" if t.is_ai_question else "Candidate"
                    lines.append(f"{speaker}: {t.content}")
                transcript_text = "\n".join(lines)

        # 4. Build prompt
        system_instruction = """You are MeetMind, an AI assistant that helps users
            understand and extract insights from interview sessions. Answer questions based
            only on the provided transcript and context. Do not make up information."""

        user_content = f"""# JOB DESCRIPTION
            {jd}

            # EVALUATION SCORECARD
            {rubric}

            # AI ASSESSMENT
            {assessment}

            # INTERVIEW TRANSCRIPT
            {transcript_text}

            # USER QUESTION
            {query}

            # TASK
            Answer the user's question based on the interview transcript, job description,
            and assessment above. Be concise and accurate. If the information is not in the
            transcript, say so.
            """

        # 5. Call LLM
        return await generate_text(
            system_instruction=system_instruction,
            user_content=user_content,
            temperature=0.5,
            max_tokens=1000,
        )
