"""AI generation service for interview questions, assessments, and Q&A."""
# ruff: noqa: E501

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from textwrap import dedent

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import generate_structured_output, generate_text
from app.core.responses import APIError
from app.core.utils import retry_async
from app.db.session import AsyncSessionLocal
from app.models.interview import (
    Candidate,
    Interview,
    InterviewSession,
    InterviewSummary,
    InterviewTranscript,
    InterviewTranscriptTurn,
)
from app.models.user import User
from app.schemas.assessment import AssessmentOutput
from app.schemas.interview import InterviewPlanOutput
from app.services.interview import InterviewService
from app.services.interview_context_service import InterviewContextService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# Maps speaker values stored in the DB to human-readable prompt labels.
_SPEAKER_LABELS = {
    "ai": "Interviewer",
    "candidate": "Candidate",
    "user": "Recruiter (Internal Note)",
    "assistant": "AI Assistant (Internal Note)",
}

# Speakers that belong to the live interview thread.
_INTERVIEW_SPEAKERS = {"ai", "candidate"}


class AIGenerationService:
    """Generate interview questions, assessments, and answer queries."""

    @staticmethod
    async def get_interview_for_user(
        interview_id: uuid.UUID,
        user: User,
        db: AsyncSession,
    ) -> Interview:
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
        return interview

    @staticmethod
    async def _get_or_create_transcript(
        interview_id: uuid.UUID,
        db: AsyncSession,
    ) -> InterviewTranscript:
        """Return existing transcript or create a new one."""
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
        return transcript

    @staticmethod
    async def _next_sequence(
        transcript_id: uuid.UUID,
        db: AsyncSession,
    ) -> int:
        """Return the next sequence number for a transcript turn."""
        last_seq = (
            await db.execute(
                select(InterviewTranscriptTurn.sequence_no)
                .where(InterviewTranscriptTurn.transcript_id == transcript_id)
                .order_by(InterviewTranscriptTurn.sequence_no.desc())
                .limit(1)
            )
        ).scalar_one_or_none() or 0
        return last_seq + 1

    @staticmethod
    async def _retrieve_resume_context(
        candidate_id: uuid.UUID,
        job_description: str,
        db: AsyncSession,
    ) -> str:
        """Retrieve relevant resume/document chunks joined by separators."""
        retrieved = await InterviewContextService.retrieve_relevant_chunks(
            candidate_id=candidate_id,
            query=f"Candidate experience, skills, and background relevant to: {job_description}",
            db=db,
        )
        return "\n---\n".join(retrieved)

    @staticmethod
    async def _format_turns_text(
        interview_id: uuid.UUID,
        db: AsyncSession,
        include_backchannel: bool = False,
    ) -> str | None:
        """Format transcript turns as ``Speaker: content`` lines."""
        transcript = (
            await db.execute(
                select(InterviewTranscript).where(
                    InterviewTranscript.interview_id == interview_id
                )
            )
        ).scalar_one_or_none()

        turns = []
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

        # Fallback to InterviewSession transcript_json if no DB turns found
        if not turns:
            interview = await db.get(Interview, interview_id)
            if interview and interview.session_id:
                session = await db.get(InterviewSession, interview.session_id)
                if session and session.transcript_json:
                    try:
                        fallback_turns = json.loads(session.transcript_json)
                        if isinstance(fallback_turns, list):
                            if not include_backchannel:
                                fallback_turns = [
                                    t
                                    for t in fallback_turns
                                    if t.get("speaker") in _INTERVIEW_SPEAKERS
                                ]
                            if fallback_turns:
                                lines = [
                                    f"{_SPEAKER_LABELS.get(t.get('speaker', 'unknown'), 'Unknown')}: {t.get('content') or t.get('text') or ''}"
                                    for t in fallback_turns
                                ]
                                return "\n".join(lines)
                    except Exception as e:
                        logger.exception(
                            "Failed to parse fallback transcript JSON in _format_turns_text: %s",
                            e,
                        )
            return None

        if not include_backchannel:
            turns = [t for t in turns if t.speaker in _INTERVIEW_SPEAKERS]

        if not turns:
            return None

        lines = [
            f"{_SPEAKER_LABELS.get(t.speaker, 'Unknown')}: {t.content}" for t in turns
        ]
        return "\n".join(lines)

    @staticmethod
    def _add_turn(
        transcript_id: uuid.UUID,
        speaker: str,
        speaker_name: str,
        content: str,
        sequence_no: int,
        is_ai_question: bool,
    ) -> InterviewTranscriptTurn:
        """Build a transcript turn — caller is responsible for db.add()."""
        return InterviewTranscriptTurn(
            transcript_id=transcript_id,
            speaker=speaker,
            speaker_name=speaker_name,
            content=content,
            sequence_no=sequence_no,
            is_ai_question=is_ai_question,
            timestamp_sec=int(datetime.now(timezone.utc).timestamp()),
        )

    @classmethod
    async def _build_question_context(
        cls,
        candidate_id: uuid.UUID,
        job_description: str,
        scorecard: str,
        ai_tone: str | None,
        db: AsyncSession,
    ) -> str:
        try:
            resume_context = await cls._retrieve_resume_context(
                candidate_id, job_description, db
            )
        except Exception:
            logger.warning("Failed to retrieve resume context, proceeding without it")
            resume_context = "No resume context available."
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
        return dedent(f"""
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
        """).strip()

    @classmethod
    async def _build_assessment_context(
        cls,
        candidate_id: uuid.UUID,
        job_description: str,
        scorecard: str,
        db: AsyncSession,
    ) -> str:
        try:
            resume_context = await cls._retrieve_resume_context(
                candidate_id, job_description, db
            )
        except Exception:
            logger.warning(
                "Failed to retrieve resume context for assessment, proceeding without it"
            )
            resume_context = "No resume context available."
        return dedent(f"""
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
        """).strip()

    @classmethod
    async def generate_next_question(
        cls,
        interview_id: uuid.UUID,
        db: AsyncSession,
        user: User,
    ) -> str:
        """Generate the next interview question using context and conversation history."""
        interview = await cls.get_interview_for_user(interview_id, user, db)

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

        system_instruction = await cls._build_question_context(
            candidate_id=candidate.id,
            job_description=summary.job_description,
            scorecard=summary.scoring_rubric or "",
            ai_tone=interview.ai_tone,
            db=db,
        )

        turns_text = await cls._format_turns_text(interview_id, db)
        conversation_text = (
            turns_text
            if turns_text is not None
            else "No conversation yet — this is the beginning of the interview."
        )

        question = await retry_async(
            generate_text,
            system_instruction=system_instruction,
            user_content=dedent(f"""
                # CONVERSATION SO FAR
                {conversation_text}

                # TASK
                Based on the conversation so far and the scorecard criteria, generate the next
                interview question. Keep it concise and conversational for a live audio call.
                Only output the question, nothing else.
            """).strip(),
            temperature=0.7,
            max_tokens=500,
            max_retries=3,
            initial_delay=1.0,
            backoff_factor=2.0,
            task_name=f"Generate next question for interview {interview_id}",
        )

        transcript = await cls._get_or_create_transcript(interview_id, db)
        seq = await cls._next_sequence(transcript.id, db)
        db.add(
            cls._add_turn(
                transcript.id,
                "ai",
                "MeetMind",
                question,
                seq,
                is_ai_question=True,
            )
        )
        await db.commit()
        return question

    @classmethod
    async def generate_assessment(
        cls,
        interview_id: uuid.UUID,
    ) -> None:
        """Generate a post-interview assessment and persist it on the summary."""
        async with AsyncSessionLocal() as db:
            summary = None
            try:
                interview = (
                    await db.execute(
                        select(Interview).where(Interview.id == interview_id)
                    )
                ).scalar_one_or_none()
                if not interview:
                    return

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

                summary.status = "generating"
                await db.commit()

                system_instruction = await cls._build_assessment_context(
                    candidate_id=candidate.id,
                    job_description=summary.job_description,
                    scorecard=summary.scoring_rubric or "",
                    db=db,
                )

                turns_text = await cls._format_turns_text(interview_id, db)
                if turns_text is None:
                    summary.status = "failed"
                    await db.commit()
                    return

                result = await retry_async(
                    generate_structured_output,
                    system_instruction=system_instruction,
                    user_content=dedent(f"""
                        # FULL INTERVIEW TRANSCRIPT
                        {turns_text}

                        # TASK
                        Evaluate the candidate based on the transcript and scorecard above.
                        Cover each criterion, note strengths and weaknesses, flag any red flags,
                        and provide an overall recommendation.
                        
                        For each criterion in the scorecard:
                        - Assign a score (0-100)
                        - Assign a confidence level (0-100) indicating how certain you are of this score based on transcript quality, answer clarity, and evidence sufficiency
                        - List 2-4 key signals (competencies/traits detected)
                        - List 2-3 specific strengths demonstrated by the candidate for this criterion
                        - List 1-2 areas for improvement or weaknesses for this criterion
                        - List the questions asked that relate to this criterion
                        - Provide a brief justification grounded in the transcript
                        Then provide overall highlights and red flags.

                        You MUST return your response strictly as a valid JSON object.
                        Do NOT wrap the output in a parent key like "evaluation" or "data".
                        Your JSON must be flat and contain EXACTLY the following root keys:
                        - "observation" (string)
                        - "criteria" (list of objects with "name", "score" 0-100, "confidence" 0-100, "signals" list of strings, "strengths" list of strings, "weaknesses" list of strings, "questions" list of strings, "justification" string)
                        - "highlights" (list of strings)
                        - "red_flags" (list of strings)
                    """).strip(),
                    output_schema=AssessmentOutput,
                    temperature=0.3,
                    max_tokens=2000,
                    max_retries=3,
                    initial_delay=2.0,
                    backoff_factor=2.0,
                    task_name=f"Generate assessment for interview {interview_id}",
                )

                summary.ai_assessment = json.dumps(result)
                summary.status = "completed"
                summary.generated_at = datetime.now(timezone.utc)
                await db.commit()

                # Persist scorecard data so GET /scorecard returns results
                report = {
                    "criteria": [
                        {
                            "name": c["name"],
                            "percentage": c["score"],
                            "confidence": c.get("confidence", 0),
                            "questions": c.get("questions", []),
                            "signals": c.get("signals", []),
                            "strengths": c.get("strengths", []),
                            "weaknesses": c.get("weaknesses", []),
                            "justification": c.get("justification", ""),
                        }
                        for c in result.get("criteria", [])
                    ],
                    "overall": "",
                    "summary": result.get("observation", ""),
                }
                try:
                    await InterviewService._persist_scorecard_report(
                        interview, report, db
                    )
                    await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to persist scorecard for interview %s", interview_id
                    )
                    await db.rollback()

                try:
                    await NotificationService.create(
                        db=db,
                        user_id=interview.interviewer_id,
                        type="report",
                        title="Interview Summary Ready",
                        description=f"{candidate.full_name or 'Candidate'} - {interview.role_title or 'Interview'}",
                        action_url=f"/interviews/{interview_id}",
                    )
                except Exception:
                    logger.exception(
                        "Failed to create summary-ready notification for interview %s",
                        interview_id,
                    )

            except Exception:
                logger.exception(
                    "Assessment generation failed for interview %s", interview_id
                )
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
        """Answer a natural language query about an interview session."""
        await cls.get_interview_for_user(interview_id, user, db)

        summary = (
            await db.execute(
                select(InterviewSummary).where(
                    InterviewSummary.interview_id == interview_id
                )
            )
        ).scalar_one_or_none()

        jd = summary.job_description if summary else ""
        rubric = summary.scoring_rubric if summary else ""
        assessment = summary.ai_assessment if summary else ""

        turns_text = await cls._format_turns_text(
            interview_id, db, include_backchannel=True
        )
        transcript_text = (
            turns_text if turns_text is not None else "No transcript available."
        )

        return await retry_async(
            generate_text,
            system_instruction=dedent("""
                You are MeetMind, an AI assistant that helps users
                understand and extract insights from interview sessions. Answer questions based
                only on the provided transcript and context. Do not make up information.
            """).strip(),
            user_content=dedent(f"""
                # JOB DESCRIPTION
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
            """).strip(),
            temperature=0.5,
            max_tokens=1000,
            max_retries=3,
            initial_delay=1.0,
            backoff_factor=2.0,
            task_name=f"Answer query for interview {interview_id}",
        )

    @classmethod
    async def record_response(
        cls,
        interview_id: uuid.UUID,
        content: str,
        user: User,
        db: AsyncSession,
    ) -> str:
        """Save a candidate response turn and generate the next question."""
        await cls.get_interview_for_user(interview_id, user, db)

        transcript = await cls._get_or_create_transcript(interview_id, db)
        seq = await cls._next_sequence(transcript.id, db)
        db.add(
            cls._add_turn(
                transcript.id,
                "candidate",
                "Candidate",
                content,
                seq,
                is_ai_question=False,
            )
        )
        await db.commit()

        return await cls.generate_next_question(
            interview_id=interview_id, db=db, user=user
        )

    @classmethod
    async def complete_interview(
        cls,
        interview_id: uuid.UUID,
        user: User,
        db: AsyncSession,
    ) -> None:
        """Mark an interview as completed."""
        interview = await cls.get_interview_for_user(interview_id, user, db)
        interview.status = "completed"
        await db.commit()

    @classmethod
    async def send_chat_message(
        cls,
        interview_id: uuid.UUID,
        content: str,
        user: User,
        db: AsyncSession,
    ) -> dict:
        """Answer a recruiter chat message statelessly (no DB save)."""

        await cls.get_interview_for_user(interview_id, user, db)

        transcript = await cls._get_or_create_transcript(interview_id, db)
        real_next_seq = await cls._next_sequence(transcript.id, db)

        answer = await cls.answer_query(
            interview_id=interview_id,
            query=content,
            user=user,
            db=db,
        )

        return {
            "role": "assistant",
            "content": answer,
            "sent_at": datetime.now(timezone.utc),
            "sequence_no": real_next_seq + 1,
        }

    @classmethod
    async def generate_interview_plan(
        cls,
        role_title: str,
        job_description: str,
        skills_to_assess: list[str],
        custom_question: str | None = None,
    ) -> InterviewPlanOutput:
        """
        AI Shaping: Generates a structured interview plan (intro, questions, rubric)
        from raw inputs. Used during Interview Creation (T-Minus 0).
        """
        system_instruction = dedent(f"""
You are an expert Technical Recruiter. Your task is to design a high-quality 
structured interview plan for the role of '{role_title}'.

# JOB DESCRIPTION
{job_description}

# CORE SKILLS TO EVALUATE
{", ".join(skills_to_assess)}

# SPECIFIC REQUESTS
{f"Ensure you include this question/topic: {custom_question}" if custom_question else "None"}

# INSTRUCTIONS
1. Design 5 specific, high-signal interview questions.
2. For each question, provide a 'followUpHint' to help the AI bot probe deeper.
3. Create a weighted scoring rubric based on the core skills.
4. Write a concise, warm intro and a professional closing.

Keep all text suitable for a live audio call (concise and natural).
            """).strip()

        result_dict = await retry_async(
            generate_structured_output,
            system_instruction=system_instruction,
            user_content="Generate the complete interview plan based on the provided context.",
            output_schema=InterviewPlanOutput,
            temperature=0.7,
            max_tokens=2000,
            max_retries=3,
            initial_delay=2.0,
            backoff_factor=2.0,
            task_name=f"Generate interview plan for role {role_title}",
        )

        # result_dict is already a dict or Pydantic model depending on your provider implementation
        return InterviewPlanOutput.model_validate(result_dict)
